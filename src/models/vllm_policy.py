"""
VLLM Policy — OpenAI API 封装

直接复用项目一实现，增加 from __future__ import annotations 以保持 Python 3.10+ 兼容性。
接口保持完全一致：
  - __call__(messages) -> OpenAICompatibleDict
  - set_tools(tools)
  - _truncate_messages(messages, max_chars)
"""
from __future__ import annotations

import json
import random
import re
import threading
import time
from collections import deque
from typing import Optional

from openai import OpenAI

from ..utils.env_config import get_env_float


__all__ = ["VLLMPolicy", "OpenAICompatibleDict", "configure_global_request_limiter"]


class _GlobalRequestLimiter:
    """Thread-safe process-wide concurrency and rolling-RPM limiter."""

    def __init__(self) -> None:
        self.maximum = 12
        self.limit = 12
        self.rpm = 600
        self.active = 0
        self.requests: deque[float] = deque()
        self.last_429: float | None = None
        self.cooldown_until = 0.0
        self.condition = threading.Condition()

    def configure(self, concurrency: int, rpm: int, initial_concurrency: int | None = None) -> None:
        with self.condition:
            self.maximum = max(1, concurrency)
            self.limit = min(self.maximum, max(1, initial_concurrency or self.maximum))
            self.rpm = max(1, rpm)
            self.active = 0
            self.requests.clear()
            self.last_429 = None
            self.cooldown_until = 0.0
            self.condition.notify_all()

    def acquire(self) -> None:
        with self.condition:
            while True:
                now = time.monotonic()
                if now < self.cooldown_until:
                    self.condition.wait(timeout=min(1.0, self.cooldown_until - now))
                    continue
                while self.requests and now - self.requests[0] >= 60:
                    self.requests.popleft()
                if self.last_429 is not None and now - self.last_429 >= 300 and self.limit < self.maximum:
                    self.limit = min(self.maximum, self.limit * 2)
                    self.last_429 = now if self.limit < self.maximum else None
                    print(f"[QwenLimiter] recovered concurrency to {self.limit}")
                if self.active < self.limit and len(self.requests) < self.rpm:
                    self.active += 1
                    self.requests.append(now)
                    return
                wait_for = 1.0
                if len(self.requests) >= self.rpm:
                    wait_for = max(0.05, 60 - (now - self.requests[0]))
                self.condition.wait(timeout=min(wait_for, 1.0))

    def release(self) -> None:
        with self.condition:
            self.active = max(0, self.active - 1)
            self.condition.notify_all()

    def on_429(self, retry_after: float | None = None) -> None:
        with self.condition:
            self.limit = max(1, self.limit // 2)
            now = time.monotonic()
            self.last_429 = now
            cooldown = max(15.0, retry_after or 0.0)
            self.cooldown_until = max(self.cooldown_until, now + cooldown)
            print(
                f"[QwenLimiter] 429 detected; concurrency reduced to {self.limit}; "
                f"global cooldown {cooldown:.1f}s"
            )
            self.condition.notify_all()

    def snapshot(self) -> dict[str, int]:
        with self.condition:
            return {"limit": self.limit, "maximum": self.maximum, "rpm": self.rpm, "active": self.active}


_GLOBAL_REQUEST_LIMITER = _GlobalRequestLimiter()


def configure_global_request_limiter(
    concurrency: int = 12, rpm: int = 600, initial_concurrency: int | None = None
) -> None:
    _GLOBAL_REQUEST_LIMITER.configure(concurrency, rpm, initial_concurrency)


def _retry_after_seconds(error: Exception) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(0.0, float(value)) if value is not None else None
    except (TypeError, ValueError):
        return None


# 正则表达式：用于抠出 Qwen 在标签外输出废话时的工具指令
TOOL_CALL_PATTERN = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)

# [质量过滤器] Assistant 绝不应该输出这些模板标记
# 如果检测到，整条 trajectory 标记为污染（复用 was_truncated 通道）
FORBIDDEN_TEMPLATE_TOKENS = ["</tool_response>", "<tool_response>"]


# 万能兼容类：让字典支持 .content 和 .tool_calls 访问
class OpenAICompatibleDict(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__dict__ = self


class VLLMPolicy:
    """VLLM Policy：封装 OpenAI 兼容 API（vLLM / OpenAI）。

    核心能力:
      - 消息格式清洗与合并（防止 vLLM 400）
      - 主动截断（保留 system + 最近交互，丢弃旧轮次）
      - 工具调用解析（原生 + 正则回退）
      - 错误分类处理（上下文超限抛异常，其他错误返回假 assistant）
    """

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-7B-Instruct",
        base_url: str = "http://localhost:8000/v1",
        api_key: str = "EMPTY",
        temperature: float = 0.0,
        top_p: float = 1.0,
        max_tokens: int = 1024,
        tools: Optional[list[dict]] = None,
        max_retries: int = 2,
        strict_errors: bool = False,
        timeout: float | None = None,
    ):
        raw_client = OpenAI(
            base_url=base_url,
            api_key=api_key,
            timeout=timeout or get_env_float("QWEN_REQUEST_TIMEOUT", 60.0),
        )
        # 如果 LangSmith 追踪开启，自动包装 client 以追踪所有 LLM 调用
        from ..utils.tracing import maybe_wrap_openai_client
        self.client = maybe_wrap_openai_client(raw_client)
        self.model_name = model_name
        self.temperature = temperature
        self.top_p = top_p
        self.max_tokens = max_tokens
        self.tools = tools
        self.max_retries = max(0, max_retries)
        self.strict_errors = strict_errors
        # [污染标记] 一旦发生过主动截断，整条 trajectory 作废
        self.was_truncated = False
        self.usage_totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "usage_estimated": False,
        }

    def set_tools(self, tools: list[dict]) -> None:
        """注册可用工具（OpenAI function calling schema）。"""
        self.tools = tools

    def _truncate_messages(self, messages: list, max_chars: int = 35000) -> list:
        """主动截断：保留 system + 最近交互，逐步丢弃旧轮次。

        阈值 35000 字符 ≈ 11-12K content tokens（ratio 2.5-3.0 + overhead + tool metadata）。
        截断是"丢弃旧轮次"而非截断内容，避免在消息中间切断导致语义破碎。
        """
        system_msgs = [m for m in messages if isinstance(m, dict) and m.get("role") == "system"]
        other_msgs = [m for m in messages if not (isinstance(m, dict) and m.get("role") == "system")]

        def _count_chars(msgs):
            total = 0
            for m in msgs:
                if not isinstance(m, dict):
                    continue
                # 1. content 字符数
                total += len(str(m.get("content", "")))
                # 2. assistant message 的 tool_calls 中 arguments + name（这些是 token 大户但被遗漏）
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    for tc in m["tool_calls"]:
                        func = tc.get("function", {})
                        total += len(str(func.get("arguments", "")))
                        total += len(str(func.get("name", "")))
                # 3. tool message 的 metadata（较短但也计入）
                if m.get("role") == "tool":
                    total += len(str(m.get("tool_call_id", "")))
                    total += len(str(m.get("name", "")))
            return total

        before_chars = _count_chars(messages)
        if before_chars <= max_chars:
            return messages

        self.was_truncated = True
        print(f"[TRUNCATE] Triggered: {before_chars} chars > {max_chars} threshold. n_msgs={len(messages)}")
        print(f"[TRUNCATE] System msgs: {len(system_msgs)}, Other msgs: {len(other_msgs)}")

        # 策略：从 other_msgs 的头部开始丢弃旧消息，保留最近交互
        # 但保证至少保留 system + 最近 3 条（否则上下文完全丢失）
        # 关键：不能拆开 assistant(tool_calls) 和后面紧跟的 tool 消息
        kept = list(other_msgs)
        while len(kept) > 3:
            removed = kept.pop(0)
            # 如果丢弃了带 tool_calls 的 assistant，后面连续的 tool 消息也必须一起丢
            if isinstance(removed, dict) and removed.get("role") == "assistant" and removed.get("tool_calls"):
                while kept and isinstance(kept[0], dict) and kept[0].get("role") == "tool":
                    kept.pop(0)
            after_chars = _count_chars(system_msgs + kept)
            if after_chars <= max_chars:
                print(f"[TRUNCATE] Reduced to {after_chars} chars, kept {len(kept)} non-system msgs")
                return system_msgs + kept

        # 极端情况：即使只保留 system + 最后 3 条也超阈值
        # 对最后一条（最新的交互）做内容级截断兜底
        after_chars = _count_chars(system_msgs + kept)
        if after_chars > max_chars and kept:
            # 截断最后一条 message 的 content（通常是超长的 tool result）
            last_msg = kept[-1]
            excess = after_chars - max_chars
            content = str(last_msg.get("content", ""))
            new_len = max(len(content) - excess - 100, 500)  # 留 100 字符缓冲，至少保留 500
            last_msg["content"] = content[:new_len] + "\n[CONTENT_TRUNCATED]"
            final_chars = _count_chars(system_msgs + kept)
            print(f"[TRUNCATE] Content-truncated last msg to {new_len} chars. Final: {final_chars}")
            return system_msgs + kept

        return system_msgs + kept

    def __call__(self, messages: list) -> OpenAICompatibleDict:
        """调用 LLM，返回 OpenAI 兼容格式消息。

        Args:
            messages: OpenAI 格式的消息列表。

        Returns:
            OpenAICompatibleDict: 包含 role, content, tool_calls 字段。
        """
        # 1. 深度清洗消息格式
        sanitized = []
        for m in messages:
            role, content = "user", ""
            if isinstance(m, dict):
                role, content = m.get("role", "user"), m.get("content", "")
            elif isinstance(m, (list, tuple)) and len(m) == 2:
                # 修复核心报错：处理 ['observation', '...'] 这种元组格式
                role = "user" if m[0] in ["observation", "user"] else "assistant"
                content = str(m[1])

            # 过滤环境内部泄露的 Task 对象信息，防止干扰模型
            if "task=Task(" in str(content):
                continue

            new_msg = {"role": role, "content": str(content)}
            # 保留 assistant 的 tool_calls 和 tool 的元数据，否则 vLLM 会报 400
            if role == "assistant" and m.get("tool_calls"):
                new_msg["tool_calls"] = m["tool_calls"]
            # 保留 reasoning_content（DeepSeek 推理模型需要）
            if role == "assistant" and m.get("reasoning_content"):
                new_msg["reasoning_content"] = m["reasoning_content"]
            if role == "tool":
                new_msg["tool_call_id"] = m.get("tool_call_id", "")
                new_msg["name"] = m.get("name", "")

            # 合并连续的同角色消息，防止 vLLM 400 报错
            # 但包含 tool_calls / tool_call_id 的消息不能合并，否则字段会丢失
            can_merge = (
                sanitized
                and sanitized[-1]["role"] == role
                and role in ("user", "assistant")
                and "tool_calls" not in sanitized[-1]
                and "tool_calls" not in new_msg
                and "tool_call_id" not in new_msg
            )
            if can_merge:
                sanitized[-1]["content"] += "\n" + str(content)
            else:
                sanitized.append(new_msg)

        # 2. 主动截断（16K 约束下的质量过滤器）
        # 阈值 12-13K content tokens ≈ 40000 字符（ratio 2.8-3.2 + overhead）
        sanitized = self._truncate_messages(sanitized, max_chars=35000)

        # 3. 发送请求
        kwargs = dict(
            model=self.model_name,
            messages=sanitized,
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
        )
        if self.tools:
            kwargs["tools"] = self.tools
            kwargs["tool_choice"] = "auto"

        try:
            resp = None
            for attempt in range(self.max_retries + 1):
                _GLOBAL_REQUEST_LIMITER.acquire()
                try:
                    resp = self.client.chat.completions.create(**kwargs)
                    break
                except Exception as request_error:
                    status = getattr(request_error, "status_code", None)
                    retryable = status in {429, 500, 502, 503, 504} or "timeout" in str(request_error).lower()
                    retry_after = _retry_after_seconds(request_error)
                    if status == 429:
                        _GLOBAL_REQUEST_LIMITER.on_429(retry_after)
                    if attempt >= self.max_retries or not retryable:
                        raise
                    delay = retry_after if retry_after is not None else (5, 15)[attempt]
                    time.sleep(delay + random.uniform(0, min(1.0, delay * 0.1)))
                finally:
                    _GLOBAL_REQUEST_LIMITER.release()
            if resp is None:
                raise RuntimeError("Model request returned no response")
            raw_msg = resp.choices[0].message
            content = raw_msg.content or ""

            # 4. [FORBIDDEN] 检测 assistant 是否输出了不该出现的模板标记
            for forbidden in FORBIDDEN_TEMPLATE_TOKENS:
                if forbidden in content:
                    print(f"[FORBIDDEN] Detected '{forbidden}' in assistant content, marking trajectory as contaminated")
                    self.was_truncated = True
                    break

            # 5. 解析工具调用 (带正则回退)
            final_tool_calls = []
            if raw_msg.tool_calls:
                for tc in raw_msg.tool_calls:
                    final_tool_calls.append(OpenAICompatibleDict(
                        id=tc.id, type="function",
                        function=OpenAICompatibleDict(name=tc.function.name, arguments=tc.function.arguments)
                    ))
            elif "<tool_call>" in content:
                matches = TOOL_CALL_PATTERN.findall(content)
                for i, m_str in enumerate(matches):
                    try:
                        d = json.loads(m_str.strip())
                        final_tool_calls.append(OpenAICompatibleDict(
                            id=f"manual_{i}", type="function",
                            function=OpenAICompatibleDict(name=d.get("name"), arguments=json.dumps(d.get("arguments", {})))
                        ))
                    except Exception:
                        continue

            # 6. 返回万能对象
            raw_usage = getattr(resp, "usage", None)
            if raw_usage is not None:
                usage = {
                    "input_tokens": int(getattr(raw_usage, "prompt_tokens", 0) or 0),
                    "output_tokens": int(getattr(raw_usage, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(raw_usage, "total_tokens", 0) or 0),
                    "usage_estimated": False,
                }
            else:
                input_estimate = len(json.dumps(sanitized, ensure_ascii=False)) // 3
                output_estimate = len(content) // 3
                usage = {
                    "input_tokens": input_estimate,
                    "output_tokens": output_estimate,
                    "total_tokens": input_estimate + output_estimate,
                    "usage_estimated": True,
                }
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                self.usage_totals[key] += usage[key]
            self.usage_totals["usage_estimated"] = self.usage_totals["usage_estimated"] or usage["usage_estimated"]
            result = OpenAICompatibleDict(role="assistant", content=content, tool_calls=final_tool_calls, usage=usage)
            if getattr(raw_msg, "reasoning_content", None):
                result["reasoning_content"] = raw_msg.reasoning_content
            return result

        except Exception as e:
            err_str = str(e)
            err_lower = err_str.lower()
            print(f"Policy Error: {err_str}")

            # Context 超限：确定性错误，立刻中止 trajectory（不继续浪费采样）
            if "maximum context length" in err_lower or "context length" in err_lower:
                n_msgs = len(messages)
                total_chars = sum(len(str(m.get("content", ""))) for m in messages if isinstance(m, dict))
                raise RuntimeError(
                    f"[CONTEXT_LENGTH_EXCEEDED] n_msgs={n_msgs}, est_chars={total_chars}: {err_str}"
                ) from e

            if self.strict_errors:
                raise RuntimeError(f"[MODEL_REQUEST_FAILED] {err_str}") from e

            # 其他错误（网络抖动、vLLM 临时 busy 等）：返回假 assistant，让 trajectory 有机会继续
            return OpenAICompatibleDict(
                role="assistant",
                content=f"Error: {err_str}",
                tool_calls=[]
            )
