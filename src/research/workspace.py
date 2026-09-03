"""Evidence-aware follow-up planning between research rounds."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.evidence.schemas import ResearchRound
from src.orchestrator.schemas import AgentResult, AgentStatus, SubTask, TaskType


@dataclass
class WorkspaceAssessment:
    should_continue: bool
    followup_tasks: list[SubTask] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    source_count: int = 0
    claim_count: int = 0
    supported_claim_count: int = 0
    stop_reason: str = ""


class ResearchWorkspace:
    """Builds a compact workspace and targeted evidence follow-ups.

    The controller does not ask an LLM to repeat the whole plan. It identifies
    tasks with failures or insufficient primary evidence and creates bounded
    verification tasks. This keeps the additional round observable and cheap.
    """

    def __init__(self) -> None:
        self.rounds: list[ResearchRound] = []
        self._last_source_count = -1

    def reset(self) -> None:
        self.rounds.clear()
        self._last_source_count = -1

    def assess(
        self,
        round_id: int,
        results: list[AgentResult],
        task_map: dict[str, SubTask],
        min_sources_per_task: int,
        max_followup_tasks: int,
        may_continue: bool,
    ) -> WorkspaceAssessment:
        unique_sources = {
            source.get("url") or source.get("content_hash")
            for result in results
            for source in result.sources
            if source.get("url") or source.get("content_hash")
        }
        all_claims = [claim for result in results for claim in result.claims]
        supported = sum(
            claim.get("verification_status") == "supported" for claim in all_claims
        )

        weak: list[tuple[AgentResult, SubTask | None]] = []
        for result in results:
            task = task_map.get(result.task_id)
            source_count = len(
                {
                    source.get("url") or source.get("content_hash")
                    for source in result.sources
                    if source.get("url") or source.get("content_hash")
                }
            )
            if result.status != AgentStatus.SUCCESS or source_count < min_sources_per_task:
                weak.append((result, task))

        no_progress = self._last_source_count >= 0 and len(unique_sources) <= self._last_source_count
        followups: list[SubTask] = []
        unresolved: list[str] = []
        if may_continue and weak and not no_progress:
            for index, (result, task) in enumerate(weak[:max_followup_tasks], 1):
                description = task.description if task else str(result.output)[:180]
                unresolved.append(description)
                followups.append(
                    SubTask(
                        task_id=f"round_{round_id + 1}_verify_{index}",
                        task_type=TaskType.VERIFY,
                        description=(
                            f"Verify this technology-research point using at least {min_sources_per_task} "
                            f"primary or official sources. Extract exact supporting passages and resolve conflicts: {description}"
                        ),
                        timeout_seconds=180,
                        expected_type="verification",
                        search_hints=list(task.search_hints) if task else [],
                        source_requirements=["paper", "official_doc", "official_repository"],
                        verification_required=True,
                    )
                )

        if followups:
            stop_reason = ""
        elif not may_continue:
            stop_reason = "max_research_rounds_reached"
        elif no_progress:
            stop_reason = "no_new_evidence"
        elif not weak:
            stop_reason = "evidence_requirements_satisfied"
        else:
            stop_reason = "no_actionable_followup"

        assessment = WorkspaceAssessment(
            should_continue=bool(followups),
            followup_tasks=followups,
            unresolved_questions=unresolved,
            source_count=len(unique_sources),
            claim_count=len(all_claims),
            supported_claim_count=supported,
            stop_reason=stop_reason,
        )
        self._last_source_count = max(self._last_source_count, len(unique_sources))
        self.rounds.append(
            ResearchRound(
                round_id=round_id,
                task_ids=[result.task_id for result in results],
                source_count=assessment.source_count,
                claim_count=assessment.claim_count,
                supported_claim_count=assessment.supported_claim_count,
                unresolved_questions=assessment.unresolved_questions,
                next_actions=[task.description for task in followups],
                stop_reason=assessment.stop_reason,
            )
        )
        return assessment

    def compact_context(self, max_claims: int = 20) -> str:
        if not self.rounds:
            return ""
        latest = self.rounds[-1]
        lines = [
            f"Research round: {latest.round_id}",
            f"Sources collected: {latest.source_count}",
            f"Claims extracted: {latest.claim_count}",
            f"Supported claims: {latest.supported_claim_count}",
        ]
        if latest.unresolved_questions:
            lines.append("Unresolved questions:")
            lines.extend(f"- {item}" for item in latest.unresolved_questions[:max_claims])
        return "\n".join(lines)
