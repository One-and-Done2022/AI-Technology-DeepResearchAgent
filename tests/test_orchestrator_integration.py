from __future__ import annotations

import asyncio
import json

from src.evidence.store import EvidenceStore
from src.orchestrator.agent_pool import AgentPool
from src.orchestrator.orchestrator import Orchestrator
from src.orchestrator.schemas import RunConfig
from src.planner.planner import Planner
from src.tools.web_search import MockWebSearchTool


class PlannerPolicy:
    def __call__(self, messages):
        return {
            "content": json.dumps(
                {
                    "sub_tasks": [
                        {
                            "task_id": "task_1",
                            "task_type": "search",
                            "description": "Research Transformer architecture",
                            "dependencies": [],
                            "search_hints": ["transformer"],
                            "source_requirements": ["paper"],
                        }
                    ]
                }
            )
        }


class WorkerPolicy:
    def __init__(self) -> None:
        self.calls = 0
        self.tools = None

    def set_tools(self, tools) -> None:
        self.tools = tools

    def __call__(self, messages):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "search-1",
                        "function": {
                            "name": "web_search",
                            "arguments": json.dumps({"query": "transformer"}),
                        },
                    }
                ],
            }
        return {
            "content": "The Transformer is based on attention mechanisms. Confidence: 0.8",
            "tool_calls": [],
        }


class SummarizerPolicy:
    def __init__(self) -> None:
        self.tools = None

    def __call__(self, messages):
        return {
            "content": "The Transformer is based on attention mechanisms [S1].",
            "tool_calls": [],
        }


def test_orchestrator_persists_structured_evidence(tmp_path) -> None:
    planner = Planner(PlannerPolicy())
    pool = AgentPool(
        policy_factory=WorkerPolicy,
        tools_factory=lambda: [MockWebSearchTool(delay_ms=(0, 0))],
    )
    store = EvidenceStore(str(tmp_path / "evidence.db"))
    orchestrator = Orchestrator(
        planner=planner,
        agent_pool=pool,
        summarizer_policy=SummarizerPolicy(),
        evidence_store=store,
    )
    report = asyncio.run(
        orchestrator.run(
            "Research Transformer architecture",
            RunConfig(
                enable_iterative_research=True,
                max_research_rounds=1,
                min_sources_per_task=1,
            ),
        )
    )
    assert report.run_id.startswith("techresearch-")
    assert report.sources
    assert report.claims
    assert report.evidence_metrics["citation_coverage"] == 1.0
    assert report.runtime_metrics["subtask_success_count"] == 1
    assert store.load_report(report.run_id) is not None
    assert all(stats["active"] == 0 for stats in pool.get_stats().values())
