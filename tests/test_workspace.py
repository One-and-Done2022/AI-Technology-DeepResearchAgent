from __future__ import annotations

from src.orchestrator.schemas import AgentResult, AgentStatus, SubTask, TaskType
from src.research.workspace import ResearchWorkspace


def test_workspace_creates_bounded_followup_for_weak_evidence() -> None:
    workspace = ResearchWorkspace()
    task = SubTask(
        task_id="task_1",
        task_type=TaskType.SEARCH,
        description="Compare two inference engines",
        search_hints=["vLLM", "SGLang"],
    )
    result = AgentResult(
        task_id="task_1",
        status=AgentStatus.SUCCESS,
        output="Only one source was found.",
        sources=[{"url": "https://example.org/one"}],
    )
    assessment = workspace.assess(
        round_id=1,
        results=[result],
        task_map={task.task_id: task},
        min_sources_per_task=2,
        max_followup_tasks=1,
        may_continue=True,
    )
    assert assessment.should_continue
    assert len(assessment.followup_tasks) == 1
    assert assessment.followup_tasks[0].verification_required


def test_workspace_stops_when_evidence_requirement_is_met() -> None:
    workspace = ResearchWorkspace()
    result = AgentResult(
        task_id="task_1",
        status=AgentStatus.SUCCESS,
        output="Enough evidence.",
        sources=[{"url": "https://a.example"}, {"url": "https://b.example"}],
    )
    assessment = workspace.assess(
        round_id=1,
        results=[result],
        task_map={},
        min_sources_per_task=2,
        max_followup_tasks=2,
        may_continue=True,
    )
    assert not assessment.should_continue
    assert assessment.stop_reason == "evidence_requirements_satisfied"
