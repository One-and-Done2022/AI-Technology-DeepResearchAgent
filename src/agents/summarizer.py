"""
合成 Agent (SummarizerAgent)

将多个 SubTask 的执行结果合成为结构化的研究报告。
区别于 ResearcherAgent 的多轮 tool-calling，Summarizer 是单轮长上下文生成任务：
  - 把所有子结果按置信度排序后拼接为上下文
  - 调用 LLM 一次性生成 Markdown 格式报告
  - 提取引用来源，计算整体置信度
"""
from __future__ import annotations

from typing import Any

from .base_agent import BaseAgent
from ..evidence.extractor import EvidencePipeline
from ..orchestrator.schemas import SubTask, AgentResult, AgentStatus, ResearchReport
from ..utils.tracing import trace_agent


__all__ = ["SummarizerAgent"]


class SummarizerAgent(BaseAgent):
    """合成 Agent：将子任务结果合成为最终研究报告。

    Attributes:
        max_output_tokens: 报告生成的最大 token 数（通过 policy.max_tokens 控制）。
    """

    def __init__(self, name: str, policy, tools: list | None = None) -> None:
        super().__init__(name, policy, tools)
        self.evidence_pipeline = EvidencePipeline()

    @trace_agent(name="summarizer.run", tags=["agent", "summarizer"])
    async def run(self, task: SubTask, context: dict) -> AgentResult:
        """执行合成任务。

        Args:
            task: 通常是一个特殊的 "synthesize" 类型任务。
            context: 全局上下文，必须包含 "results" 和 "query" 键。
                results: list[AgentResult]
                query: str 原始研究问题

        Returns:
            AgentResult，output 字段为 ResearchReport 实例。
        """
        query = context.get("query", "")
        results: list[AgentResult] = context.get("results", [])

        if not results:
            report = ResearchReport(
                query=query,
                content="No sub-task results available to synthesize.",
                confidence=0.0,
            )
            return AgentResult(
                task_id=task.task_id,
                status=AgentStatus.FAILED,
                output=report,
                trajectory=[],
                token_usage=0,
                confidence=0.0,
            )

        # 构建 synthesis prompt
        sources = self._collect_sources(results)
        prompt = self._build_synthesis_prompt(query, results, sources)
        messages = [
            {"role": "system", "content": self._system_prompt()},
            {"role": "user", "content": prompt},
        ]

        try:
            # 合成任务不需要工具调用，临时禁用 tools 避免模型进入 tool-calling 模式
            old_tools = getattr(self.policy, "tools", None)
            self.policy.tools = None
            response = self.policy(messages)
            self.policy.tools = old_tools
        except RuntimeError as e:
            return AgentResult(
                task_id=task.task_id,
                status=AgentStatus.FAILED,
                output=str(e),
                trajectory=[{"error": str(e)}],
                token_usage=0,
                confidence=0.0,
            )

        content = response.get("content", "") or ""
        token_usage = len(content) // 3  # 简化估算

        # 解析报告内容，提取来源和置信度
        report = self._parse_report(query, content, results, sources)

        return AgentResult(
            task_id=task.task_id,
            status=AgentStatus.SUCCESS,
            output=report,
            trajectory=[{"role": "assistant", "content": content}],
            token_usage=token_usage,
            confidence=report.confidence,
        )

    def _system_prompt(self) -> str:
        return (
            "You are the synthesis component of an AI technology intelligence system. "
            "Write a concise but complete Markdown report for AI, software systems, or open-source technology research. "
            "Every factual or quantitative claim must cite one or more evidence catalog IDs such as [S1]. "
            "Never create a source ID that is not in the catalog. Distinguish verified facts, analysis, and uncertainty. "
            "When evidence conflicts, describe the conflict instead of silently choosing a side. "
            "Report length must follow available evidence; do not pad the answer to a fixed length."
        )

    def _build_synthesis_prompt(
        self,
        query: str,
        results: list[AgentResult],
        sources: list[dict[str, Any]],
    ) -> str:
        """构建合成 prompt，按置信度降序排列结果。"""
        sorted_results = sorted(results, key=lambda r: r.confidence, reverse=True)

        parts = [
            f"# Research Question\n{query}\n",
            f"# Sub-task Results ({len(results)} total)\n",
        ]
        for i, r in enumerate(sorted_results, 1):
            status_icon = "✓" if r.status == AgentStatus.SUCCESS else "✗"
            parts.append(
                f"## Result {i} [{status_icon}] (confidence: {r.confidence:.2f})\n"
                f"Task: {r.task_id}\n"
                f"Output:\n{r.output}\n"
            )

        parts.append(f"\n# Evidence Catalog ({len(sources)} sources)\n")
        for source in sources:
            parts.append(
                f"[{source['source_id']}] {source.get('title') or 'Untitled'}\n"
                f"URL: {source.get('url', '')}\n"
                f"Type: {source.get('source_type', 'unknown')} | Quality: {source.get('quality_score', 0):.2f}\n"
                f"Evidence excerpt: {(source.get('quote') or source.get('snippet', ''))[:1200]}\n"
            )

        parts.append(
            "\n# Instructions\n"
            "1. Directly write the report; do not describe a future plan.\n"
            "2. Use this structure: Executive Summary → Scope/As-of Date → Key Findings → Technical Comparison → Risks/Unknowns → Recommendation.\n"
            "3. Put [S#] immediately after every factual, quantitative, version, performance, or ecosystem claim.\n"
            "4. Use only evidence catalog IDs. If evidence is insufficient, explicitly write '证据不足'.\n"
            "5. Explain source conflicts and avoid converting inference into fact.\n"
            "6. For technology selection questions, include a comparison table.\n"
            "7. End with a short confidence and limitations section."
        )
        return "\n".join(parts)

    def _parse_report(
        self,
        query: str,
        content: str,
        results: list[AgentResult],
        sources: list[dict[str, Any]],
    ) -> ResearchReport:
        """从 LLM 输出中解析 ResearchReport，并基于子任务成功率校准置信度。"""
        # 基于子任务成功率和可验证证据计算置信度，避免依赖模型自评。
        total = len(results)
        success = sum(1 for r in results if r.status == AgentStatus.SUCCESS)
        success_rate = success / max(total, 1)

        claims, evidence_metrics = self.evidence_pipeline.refresh(content, sources)
        evidence_confidence = float(evidence_metrics.get("citation_entailment", 0.0))
        citation_coverage = float(evidence_metrics.get("citation_coverage", 0.0))
        confidence = round(
            max(0.0, min(1.0, 0.4 * success_rate + 0.4 * evidence_confidence + 0.2 * citation_coverage)),
            3,
        )

        # 统计实际工具调用次数（遍历所有子任务的 trajectory）
        num_searches = sum(
            len([t for t in r.trajectory if t.get("role") == "tool"])
            for r in results
        )

        return ResearchReport(
            query=query,
            content=content,
            sources=sources,
            confidence=confidence,
            num_searches=num_searches,
            claims=claims,
            evidence_metrics=evidence_metrics,
        )

    @staticmethod
    def _collect_sources(results: list[AgentResult]) -> list[dict[str, Any]]:
        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for result in results:
            if result.status != AgentStatus.SUCCESS:
                continue
            for raw in result.sources:
                source = dict(raw)
                key = str(source.get("url") or source.get("content_hash") or "")
                if not key or key in seen:
                    continue
                seen.add(key)
                source["source_id"] = f"S{len(unique) + 1}"
                source.setdefault("quote", source.get("snippet", ""))
                source.setdefault("snippet", source.get("quote", ""))
                source["task_id"] = result.task_id
                unique.append(source)
        return unique
