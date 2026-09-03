"""
AI Technology Research Agent — 核心编排器

状态机驱动的异步任务编排引擎：
  IDLE → PLANNING → DISPATCHING → COLLECTING → SYNTHESIZING → DONE
  失败时进入 REPLANNING，最终可进入 FAILED。

设计亮点:
  - 自研 asyncio + DAG executor，不依赖 LangGraph/AutoGen
  - 拓扑排序后按层并发执行，Semaphore 控制最大并发度
  - 三级降级策略：单任务超时→标记继续；>50%失败→re-plan；全局超时→强制合成
  - 状态机用字典映射实现，便于扩展新状态和转换逻辑
"""
from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Callable

from .schemas import (
    OrchestratorState,
    SubTask,
    AgentResult,
    AgentStatus,
    ResearchReport,
    RunConfig,
    TaskType,
)
from .agent_pool import AgentPool
from ..planner.dag import DAG
from ..planner.planner import Planner, PlanParseError
from ..planner.budget_tracker import BudgetTracker
from ..utils.tracing import trace_chain
from ..evidence.extractor import EvidencePipeline
from ..research.workspace import ResearchWorkspace

__all__ = ["Orchestrator"]


class Orchestrator:
    """Deep Research Agent 核心编排器。

    Attributes:
        planner: 自适应规划器，负责初始规划和增量重规划。
        agent_pool: Agent 对象池，管理 worker agent 生命周期。
        budget_tracker: Token 预算追踪器。
        evidence_store: 持久化来源、claims 和评测指标。
    """

    def __init__(
        self,
        planner: Planner,
        agent_pool: AgentPool,
        budget_tracker: BudgetTracker | None = None,
        summarizer_policy: Any | None = None,
        evidence_store: Any | None = None,
        evidence_pipeline: EvidencePipeline | None = None,
    ) -> None:
        self.planner = planner
        self.agent_pool = agent_pool
        self.budget_tracker = budget_tracker or BudgetTracker()
        self.summarizer_policy = summarizer_policy
        self.evidence_store = evidence_store
        self.evidence_pipeline = evidence_pipeline or EvidencePipeline()
        self.research_workspace = ResearchWorkspace()

        self._runtime_state: dict[str, Any] = {}
        self._results: list[AgentResult] = []
        self._all_results: list[AgentResult] = []
        self._dag: DAG | None = None
        self._task_map: dict[str, SubTask] = {}
        self._current_state = OrchestratorState.IDLE
        self._query: str = ""
        self._config: RunConfig = RunConfig()
        self._start_time: float = 0.0
        self._replan_count: int = 0
        self._research_round: int = 1
        self._run_id: str = ""

        # 状态机处理器映射
        self._state_handlers: dict[OrchestratorState, Callable[[], asyncio.Future[OrchestratorState]]] = {
            OrchestratorState.IDLE: self._on_idle,
            OrchestratorState.PLANNING: self._do_planning,
            OrchestratorState.DISPATCHING: self._do_dispatching,
            OrchestratorState.COLLECTING: self._do_collecting,
            OrchestratorState.SYNTHESIZING: self._do_synthesizing,
            OrchestratorState.REPLANNING: self._do_replanning,
            OrchestratorState.DONE: self._on_done,
            OrchestratorState.FAILED: self._on_failed,
        }

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    @trace_chain(name="orchestrator.run", tags=["m1", "orchestrator"])
    async def run(self, query: str, config: RunConfig | None = None) -> ResearchReport:
        """主入口：执行完整的研究流程。

        Args:
            query: 研究问题。
            config: 运行配置，默认使用 RunConfig()。

        Returns:
            ResearchReport: 最终研究报告。
        """
        self._query = query
        self._config = config or RunConfig()
        self._start_time = time.monotonic()
        self._replan_count = 0
        self._runtime_state.clear()
        self._results.clear()
        self._all_results.clear()
        self._dag = None
        self._task_map.clear()
        self._current_state = OrchestratorState.IDLE
        self._research_round = 1
        self._run_id = f"techresearch-{uuid.uuid4().hex[:12]}"
        self.research_workspace.reset()

        # 状态机主循环
        while self._current_state not in (OrchestratorState.DONE, OrchestratorState.FAILED):
            # 全局超时检查
            if self._is_global_timeout():
                if self._all_results or self._results:
                    self._runtime_state["final_report"] = self._build_partial_report(
                        "global_timeout"
                    )
                    self._current_state = OrchestratorState.DONE
                else:
                    self._current_state = OrchestratorState.FAILED
                break

            handler = self._state_handlers.get(self._current_state)
            if handler is None:
                raise RuntimeError(f"Unknown state: {self._current_state}")

            next_state = await handler()
            self._current_state = next_state

            print(f"[Orchestrator] State transition: {self._current_state.value}")

        # 返回结果
        if self._current_state == OrchestratorState.DONE:
            # 最终报告应在 memory 中
            report = self._runtime_state.get("final_report")
            if report is None:
                report = ResearchReport(query=query, content="Report generation failed unexpectedly.")
            report.num_replan = self._replan_count
            report.run_id = self._run_id
            report.research_rounds = [item.to_dict() for item in self.research_workspace.rounds]
            elapsed = time.monotonic() - self._start_time
            report.runtime_metrics.update({
                "elapsed_seconds": round(elapsed, 3),
                "token_usage": sum(result.token_usage for result in self._all_results),
                "tool_calls": sum(
                    1
                    for result in self._all_results
                    for step in result.trajectory
                    if step.get("role") == "tool"
                ),
                "subtask_count": len(self._all_results),
                "subtask_success_count": sum(
                    result.status == AgentStatus.SUCCESS for result in self._all_results
                ),
                "research_round_count": len(self.research_workspace.rounds),
            })

            if self.evidence_store is not None:
                try:
                    self.evidence_store.save_report(
                        run_id=report.run_id,
                        query=report.query,
                        content=report.content,
                        sources=report.sources,
                        claims=report.claims,
                        metrics={**report.evidence_metrics, **report.runtime_metrics},
                    )
                except Exception as e:
                    print(f"[EvidenceStore] Failed to persist report: {e}")

            return report

        # FAILED 状态
        return ResearchReport(
            query=query,
            content="Research failed due to persistent errors or global timeout.",
            num_replan=self._replan_count,
        )

    # ------------------------------------------------------------------
    # 状态机处理器
    # ------------------------------------------------------------------

    async def _on_idle(self) -> OrchestratorState:
        """从 IDLE 自动进入 PLANNING。"""
        return OrchestratorState.PLANNING

    async def _do_planning(self) -> OrchestratorState:
        """调用 Planner 生成初始 DAG。

        失败时直接转入 FAILED（初始计划失败无法恢复）。
        """
        try:
            memory_ctx = self._build_memory_context()
            self._dag = self.planner.generate_plan(self._query, memory_ctx)
            # 从 planner 获取完整的 SubTask 信息（包括 description、search_hints 等）
            self._task_map = self.planner.get_task_map_from_dag(self._dag, self.planner._last_raw_json)
            if not self._task_map:
                # 降级：如果解析失败，使用占位符
                self._task_map = self._rebuild_task_map_from_dag()
        except PlanParseError as e:
            print(f"[Planning] Failed: {e}")
            return OrchestratorState.FAILED
        except Exception as e:
            print(f"[Planning] Unexpected error: {e}")
            return OrchestratorState.FAILED

        n_tasks = len(self._dag)
        n_layers = len(self._dag.get_parallel_groups()) if self._dag else 0
        print(f"[Planning] ✓ DAG 生成完成: {n_tasks} 个子任务, {n_layers} 个执行层")
        # 打印子任务描述以便诊断
        for tid, task in self._task_map.items():
            print(f"[Planning]   {tid}: {task.description}")
        return OrchestratorState.DISPATCHING

    async def _do_dispatching(self) -> OrchestratorState:
        """拓扑排序 + 并发调度 sub-agents。

        核心逻辑:
          1. 获取并行执行层 (parallel groups)
          2. 每层内用 asyncio.gather + Semaphore 并发执行
          3. 每个 sub-task 设置单独超时 (asyncio.wait_for)
          4. 收集结果到 self._results
        """
        if self._dag is None or len(self._dag) == 0:
            return OrchestratorState.COLLECTING

        semaphore = asyncio.Semaphore(self._config.max_concurrent)
        parallel_groups = self._dag.get_parallel_groups()
        all_results: list[AgentResult] = []

        for layer_idx, group in enumerate(parallel_groups):
            print(f"[Dispatch] ▶ Layer {layer_idx + 1}/{len(parallel_groups)}: {group} (并行执行)")

            # 构建本层的 coroutine 列表
            async def _run_one(task_id: str) -> AgentResult:
                async with semaphore:
                    subtask = self._task_map.get(task_id)
                    if subtask is None:
                        return AgentResult(
                            task_id=task_id,
                            status=AgentStatus.FAILED,
                            output=f"SubTask '{task_id}' not found in task_map",
                        )

                    # 准备上下文：先执行依赖任务的结果
                    context = self._build_task_context(subtask)

                    # 获取 Agent
                    agent = await self.agent_pool.get_agent(subtask.task_type)
                    try:
                        # 设置单任务超时
                        result = await asyncio.wait_for(
                            agent.run(subtask, context),
                            timeout=subtask.timeout_seconds,
                        )
                    except asyncio.TimeoutError:
                        result = AgentResult(
                            task_id=task_id,
                            status=AgentStatus.TIMEOUT,
                            output=f"Task timed out after {subtask.timeout_seconds}s",
                        )
                    except Exception as e:
                        result = AgentResult(
                            task_id=task_id,
                            status=AgentStatus.FAILED,
                            output=f"Exception: {type(e).__name__}: {e}",
                        )
                    finally:
                        await self.agent_pool.release_agent(agent)

                    return result

            # 并发执行本层
            coros = [_run_one(tid) for tid in group]
            layer_results = await asyncio.gather(*coros, return_exceptions=True)

            for lr in layer_results:
                if isinstance(lr, Exception):
                    # 将异常包装为 FAILED 结果
                    # 这种情况理论上不会发生（_run_one 内部已捕获），但保险起见
                    all_results.append(AgentResult(
                        task_id="unknown",
                        status=AgentStatus.FAILED,
                        output=f"Dispatch exception: {lr}",
                    ))
                else:
                    all_results.append(lr)

            # 让下一执行层立即读取本层依赖结果；旧实现要到全部层结束后才写入。
            for layer_result in all_results:
                self._runtime_state[f"result:{layer_result.task_id}"] = layer_result

        self._results = all_results
        return OrchestratorState.COLLECTING

    async def _do_collecting(self) -> OrchestratorState:
        """收集结果，写入 memory，检查是否需要重规划。

        三级降级策略检查点:
          - 单任务超时/失败：已在 dispatch 层处理（标记状态，继续执行）
          - >50% 失败：触发 REPLANNING
          - 全局超时：由外层 run() 的循环检查处理
        """
        # 将结果写入运行时 memory dict
        for r in self._results:
            self._runtime_state[f"result:{r.task_id}"] = r

        self._all_results.extend(self._results)

        success_count = sum(1 for r in self._results if r.status == AgentStatus.SUCCESS)
        total_count = len(self._results)
        fail_count = total_count - success_count
        status_icon = "✓" if success_count == total_count else "⚠"
        print(f"[Collect] {status_icon} 子任务完成: {success_count}/{total_count} 成功", end="")
        if fail_count > 0:
            print(f" ({fail_count} 失败)")
        else:
            print()

        # IterResearch：对失败或来源不足的任务发起有界定向核验轮次。
        if self._config.enable_iterative_research:
            may_continue = self._research_round < self._config.max_research_rounds
            assessment = self.research_workspace.assess(
                round_id=self._research_round,
                results=self._results,
                task_map=self._task_map,
                min_sources_per_task=self._config.min_sources_per_task,
                max_followup_tasks=self._config.max_followup_tasks,
                may_continue=may_continue,
            )
            print(
                f"[ResearchRound] round={self._research_round} sources={assessment.source_count} "
                f"claims={assessment.claim_count} followups={len(assessment.followup_tasks)} "
                f"stop={assessment.stop_reason or 'continue'}"
            )
            if assessment.should_continue:
                next_dag = DAG()
                for task in assessment.followup_tasks:
                    next_dag.add_node(task.task_id)
                self._dag = next_dag
                self._task_map = {task.task_id: task for task in assessment.followup_tasks}
                self._results = []
                self._research_round += 1
                self._runtime_state["research_workspace"] = self.research_workspace.compact_context()
                return OrchestratorState.DISPATCHING

        # 检查是否需要重规划
        if self._should_replan(self._results):
            if self._replan_count < self._config.max_replan_rounds:
                self._replan_count += 1
                return OrchestratorState.REPLANNING
            else:
                print("[Collect] Max replan rounds reached, proceeding with partial results")
                # 超过最大重规划次数，继续合成（用已有结果）

        return OrchestratorState.SYNTHESIZING

    async def _do_synthesizing(self) -> OrchestratorState:
        """调用 SummarizerAgent 合成研究报告。"""
        # 创建合成任务
        synth_task = SubTask(
            task_id="synthesize_final",
            task_type=TaskType.ANALYZE,  # 使用 ANALYZE 类型，实际由 SummarizerAgent 处理
            description="Synthesize all sub-task results into a final research report.",
            timeout_seconds=300,
        )

        synthesis_results = self._all_results or self._results
        context = {
            "query": self._query,
            "results": synthesis_results,
            "research_workspace": self.research_workspace.compact_context(),
        }

        pooled_agent = await self.agent_pool.get_agent(TaskType.ANALYZE)
        agent = pooled_agent
        release_from_pool = True
        # 需要 SummarizerAgent，但 agent_pool 可能返回 ResearcherAgent
        # 这里我们通过类型检查或强制创建 SummarizerAgent
        from ..agents.summarizer import SummarizerAgent
        if not isinstance(agent, SummarizerAgent):
            # 优先使用配置的 summarizer_policy（更大的 max_tokens），fallback 到 agent.policy
            policy = self.summarizer_policy or agent.policy
            tools = agent.tools
            await self.agent_pool.release_agent(pooled_agent)
            release_from_pool = False
            agent = SummarizerAgent(name="summarizer", policy=policy, tools=tools)
            agent.evidence_pipeline = self.evidence_pipeline

        try:
            result = await asyncio.wait_for(
                agent.run(synth_task, context),
                timeout=synth_task.timeout_seconds,
            )
        except asyncio.TimeoutError:
            result = AgentResult(
                task_id="synthesize_final",
                status=AgentStatus.TIMEOUT,
                output="Synthesis timed out",
            )
        except Exception as e:
            result = AgentResult(
                task_id="synthesize_final",
                status=AgentStatus.FAILED,
                output=f"Synthesis error: {type(e).__name__}: {e}",
            )
        finally:
            if release_from_pool:
                await self.agent_pool.release_agent(agent)

        if result.status == AgentStatus.SUCCESS and isinstance(result.output, ResearchReport):
            self._runtime_state["final_report"] = result.output
        else:
            # 合成失败但已有结果，生成降级报告
            self._runtime_state["final_report"] = ResearchReport(
                query=self._query,
                content=str(result.output) if result.output else "Synthesis failed.",
                confidence=0.0,
                num_searches=sum(
                    len([t for t in r.trajectory if t.get("role") == "tool"])
                    for r in synthesis_results
                ),
            )

        final_report = self._runtime_state.get("final_report")
        if isinstance(final_report, ResearchReport):
            final_report.research_rounds = [item.to_dict() for item in self.research_workspace.rounds]

        print("[Synthesize] ✓ 报告合成完成")
        return OrchestratorState.DONE

    async def _do_replanning(self) -> OrchestratorState:
        """触发增量重规划。

        保留 confidence≥0.6 的成功结果，修改失败子问题。
        """
        failed_tasks = []
        for r in self._results:
            if r.status != AgentStatus.SUCCESS:
                st = self._task_map.get(r.task_id)
                if st:
                    failed_tasks.append(st)

        reason = self._build_failure_reason(self._results)
        print(f"[Replan] Round {self._replan_count}/{self._config.max_replan_rounds}. Failed tasks: {[t.task_id for t in failed_tasks]}")

        try:
            new_dag = self.planner.replan(
                query=self._query,
                failed_tasks=failed_tasks,
                existing_results=self._results,
                reason=reason,
            )
            self._dag = new_dag
            self._task_map = self.planner.get_task_map_from_dag(self._dag, self.planner._last_raw_json)
            if not self._task_map:
                self._task_map = self._rebuild_task_map_from_dag()
            # 清空上一轮结果（保留在 memory 中，新任务可通过 context_keys 引用）
            self._results = []
        except PlanParseError as e:
            print(f"[Replan] Failed: {e}")
            # 重规划失败，如果已有部分成功结果，尝试直接合成
            if any(r.status == AgentStatus.SUCCESS for r in self._results):
                return OrchestratorState.SYNTHESIZING
            return OrchestratorState.FAILED
        except Exception as e:
            print(f"[Replan] Unexpected error: {e}")
            if any(r.status == AgentStatus.SUCCESS for r in self._results):
                return OrchestratorState.SYNTHESIZING
            return OrchestratorState.FAILED

        return OrchestratorState.DISPATCHING

    async def _on_done(self) -> OrchestratorState:
        """终态，不应再转换。"""
        return OrchestratorState.DONE

    async def _on_failed(self) -> OrchestratorState:
        """终态，不应再转换。"""
        return OrchestratorState.FAILED

    # ------------------------------------------------------------------
    # 决策逻辑
    # ------------------------------------------------------------------

    def _should_replan(self, results: list[AgentResult]) -> bool:
        """判断是否需要重规划。

        策略:
          - 失败率 > 50% 时触发
          - 或存在任何 TIMEOUT 且成功结果不足 30%
        """
        if not results:
            return False
        total = len(results)
        failed = sum(1 for r in results if r.status in (AgentStatus.FAILED, AgentStatus.TIMEOUT))
        success = sum(1 for r in results if r.status == AgentStatus.SUCCESS)

        failure_rate = failed / total
        if failure_rate > 0.5:
            return True
        if success / total < 0.3 and failed > 0:
            return True
        return False

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _is_global_timeout(self) -> bool:
        """检查是否超过全局超时。"""
        elapsed = time.monotonic() - self._start_time
        return elapsed > self._config.global_timeout_seconds

    def _build_memory_context(self) -> str:
        """构建给 planner 的当前运行上下文摘要。"""
        parts = []
        for key, value in self._runtime_state.items():
            if key.startswith("result:"):
                continue
            parts.append(f"{key}: {str(value)[:200]}")

        return "\n".join(parts) if parts else ""

    def _build_task_context(self, subtask: SubTask) -> dict:
        """为单个 SubTask 构建执行上下文。"""
        ctx = dict(self._runtime_state)
        ctx["query"] = self._query
        # 注入依赖任务的结果
        for dep_id in subtask.dependencies:
            dep_key = f"result:{dep_id}"
            if dep_key in self._runtime_state:
                ctx[f"dep:{dep_id}"] = self._runtime_state[dep_key]
        return ctx

    def _build_failure_reason(self, results: list[AgentResult]) -> str:
        """分析失败原因，生成给 replanner 的描述。"""
        reasons = []
        timeout_count = sum(1 for r in results if r.status == AgentStatus.TIMEOUT)
        failed_count = sum(1 for r in results if r.status == AgentStatus.FAILED)
        if timeout_count > 0:
            reasons.append(f"{timeout_count} tasks timed out (may need simpler queries or longer timeout)")
        if failed_count > 0:
            reasons.append(f"{failed_count} tasks failed with errors")
        return "; ".join(reasons) if reasons else "Unknown failure"

    def _build_partial_report(self, reason: str) -> ResearchReport:
        """Build a transparent partial report without another model call."""
        results = self._all_results or self._results
        successful = [result for result in results if result.status == AgentStatus.SUCCESS]
        lines = [
            "## 部分研究结果",
            "",
            f"> 研究未完整结束：{reason}。以下内容未经最终综合，请结合来源人工复核。",
            "",
        ]
        for result in successful:
            lines.extend([f"### {result.task_id}", "", str(result.output), ""])

        from ..agents.summarizer import SummarizerAgent

        sources = SummarizerAgent._collect_sources(successful)
        content = "\n".join(lines)
        claims, metrics = self.evidence_pipeline.refresh(content, sources)
        return ResearchReport(
            query=self._query,
            content=content,
            sources=sources,
            claims=claims,
            evidence_metrics=metrics,
            confidence=0.2 if successful else 0.0,
            num_searches=sum(
                1
                for result in results
                for step in result.trajectory
                if step.get("role") == "tool"
            ),
            runtime_metrics={"partial": True, "termination_reason": reason},
        )

    def _rebuild_task_map_from_dag(self) -> dict[str, SubTask]:
        """从 DAG 重建 task_map（当缺少原始 SubTask 信息时使用占位符）。

        实际场景中，planner 应返回完整的 SubTask 列表；
        这里作为降级：为 DAG 中每个节点创建默认 SubTask。
        """
        if self._dag is None:
            return {}

        task_map: dict[str, SubTask] = {}
        for node_id in self._dag:
            deps = self._dag.get_dependencies(node_id)
            if node_id not in self._task_map:
                # 新建占位 SubTask
                task_map[node_id] = SubTask(
                    task_id=node_id,
                    task_type=TaskType.SEARCH,
                    description=f"Auto-generated task for {node_id}",
                    dependencies=deps,
                )
            else:
                # 保留已有信息，更新依赖
                old = self._task_map[node_id]
                task_map[node_id] = SubTask(
                    task_id=old.task_id,
                    task_type=old.task_type,
                    description=old.description,
                    dependencies=deps,
                    context_keys=old.context_keys,
                    timeout_seconds=old.timeout_seconds,
                    priority=old.priority,
                    expected_type=old.expected_type,
                    search_hints=old.search_hints,
                    source_requirements=old.source_requirements,
                    verification_required=old.verification_required,
                )
        return task_map
