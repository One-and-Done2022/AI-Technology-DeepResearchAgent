"""
AI Technology Research Agent — 核心数据结构定义

所有跨模块传递的数据结构集中定义于此，保证类型一致性和可维护性。
使用 Python 3.10+ 的 | 联合类型语法。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


__all__ = [
    "OrchestratorState",
    "TaskType",
    "AgentStatus",
    "SubTask",
    "AgentResult",
    "ResearchReport",
    "RunConfig",
]


# ============================================================================
# 枚举定义
# ============================================================================

class OrchestratorState(Enum):
    """研究编排状态机。

    正常流: IDLE → PLANNING → DISPATCHING → COLLECTING → SYNTHESIZING → DONE
    异常流:
      - 局部失败 → REPLANNING (增量重规划) → DISPATCHING
      - 全局失败 / 超过最大重规划次数 → FAILED
    """
    IDLE = "idle"
    PLANNING = "planning"
    DISPATCHING = "dispatching"
    COLLECTING = "collecting"
    SYNTHESIZING = "synthesizing"
    REPLANNING = "replanning"
    DONE = "done"
    FAILED = "failed"


class TaskType(Enum):
    """Sub-task 的任务类型，决定由哪类 Agent 执行。"""
    SEARCH = "search"
    ANALYZE = "analyze"
    VERIFY = "verify"


class AgentStatus(Enum):
    """单个 Sub-task 的执行结果状态。"""
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


# ============================================================================
# 数据类定义
# ============================================================================

@dataclass
class SubTask:
    """规划器生成的原子任务单元。

    Attributes:
        task_id: 全局唯一标识，用于 DAG 依赖引用。
        task_type: 任务类型，决定调度到哪个 Agent。
        description: 自然语言描述，传给 Agent 的指令。
        dependencies: 依赖的 task_id 列表，这些任务完成后才能执行本任务。
        context_keys: 需要从当前运行上下文读取的键名。
        timeout_seconds: 单任务超时阈值（秒）。
        priority: 优先级，数值越小优先级越高。
        expected_type: 期望结果类型，辅助 Agent 调整输出格式。
        search_hints: 搜索类任务的额外关键词提示。
    """
    task_id: str
    task_type: TaskType
    description: str
    dependencies: list[str] = field(default_factory=list)
    context_keys: list[str] = field(default_factory=list)
    timeout_seconds: int = 300
    priority: int = 1
    expected_type: str = "factual"  # factual | analytical | comparative | temporal
    search_hints: list[str] = field(default_factory=list)
    source_requirements: list[str] = field(default_factory=list)
    verification_required: bool = False


@dataclass
class AgentResult:
    """Agent 执行 SubTask 后的结果。

    Attributes:
        task_id: 对应 SubTask 的 task_id。
        status: 执行状态（成功/失败/超时）。
        output: 实际输出内容，类型由任务决定（str | dict | list）。
        trajectory: 多轮交互轨迹，用于日志和后续分析。
        token_usage: 本次任务消耗的 token 数。
        confidence: 结果置信度 [0.0, 1.0]。
    """
    task_id: str
    status: AgentStatus
    output: Any = None
    trajectory: list[dict] = field(default_factory=list)
    token_usage: int = 0
    confidence: float = 0.0
    sources: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    evidence_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResearchReport:
    """最终交付给用户的研究报告。

    Attributes:
        query: 原始研究问题。
        content: 报告正文（Markdown 格式）。
        sources: 引用的信息源列表，每条包含 url/title/snippet。
        confidence: 整体置信度。
        num_searches: 实际执行的搜索/分析轮数。
        num_replan: 重规划次数。
    """
    query: str
    content: str
    sources: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    num_searches: int = 0
    num_replan: int = 0
    claims: list[dict[str, Any]] = field(default_factory=list)
    research_rounds: list[dict[str, Any]] = field(default_factory=list)
    evidence_metrics: dict[str, Any] = field(default_factory=dict)
    runtime_metrics: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""


@dataclass
class RunConfig:
    """单次运行的全局配置。

    Attributes:
        max_concurrent: 最大并发 Sub-agent 数。
        global_timeout_seconds: 全局硬超时（秒）。
        max_replan_rounds: 最大重规划轮数。
    """
    max_concurrent: int = 5
    global_timeout_seconds: int = 600
    max_replan_rounds: int = 3
    enable_iterative_research: bool = True
    max_research_rounds: int = 2
    min_sources_per_task: int = 2
    max_followup_tasks: int = 3
