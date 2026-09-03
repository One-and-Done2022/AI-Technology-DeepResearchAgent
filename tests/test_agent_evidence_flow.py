from __future__ import annotations

import asyncio
import json

from src.agents.researcher import ResearcherAgent
from src.agents.summarizer import SummarizerAgent
from src.orchestrator.schemas import AgentResult, AgentStatus, SubTask, TaskType
from src.tools.web_search import MockWebSearchTool


class ToolCallingPolicy:
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
                        "id": "call-1",
                        "function": {
                            "name": "web_search",
                            "arguments": json.dumps({"query": "transformer"}),
                        },
                    }
                ],
            }
        return {
            "content": "Transformer uses attention mechanisms. Confidence: 0.8",
            "tool_calls": [],
        }


class SynthesisPolicy:
    def __init__(self) -> None:
        self.tools = None

    def __call__(self, messages):
        return {
            "content": "Transformer is based on attention mechanisms [S1].",
            "tool_calls": [],
        }


class FailingTool:
    name = "arxiv_reader"

    def get_openai_tool_schema(self):
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": "Fails for fallback testing",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    async def execute(self, **kwargs):
        return {"error": "temporary upstream failure"}


class FallbackPolicy(ToolCallingPolicy):
    def __call__(self, messages):
        self.calls += 1
        if self.calls == 1:
            return {
                "content": "",
                "tool_calls": [
                    {"id": "paper-1", "function": {"name": "arxiv_reader", "arguments": "{}"}}
                ],
            }
        if self.calls == 2:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "search-2",
                        "function": {
                            "name": "web_search",
                            "arguments": json.dumps({"query": "transformer"}),
                        },
                    }
                ],
            }
        return {
            "content": "Transformer uses attention mechanisms. Confidence: 0.8",
            "tool_calls": [],
        }


def test_researcher_collects_structured_source() -> None:
    agent = ResearcherAgent(
        name="researcher",
        policy=ToolCallingPolicy(),
        tools=[MockWebSearchTool(delay_ms=(0, 0))],
    )
    task = SubTask(
        task_id="task_1",
        task_type=TaskType.SEARCH,
        description="Research the Transformer architecture",
    )
    result = asyncio.run(agent.run(task, {"query": task.description}))
    assert result.status == AgentStatus.SUCCESS
    assert result.sources
    assert result.sources[0]["url"].startswith("https://")


def test_summarizer_builds_claim_level_evidence() -> None:
    source = {
        "source_id": "S1",
        "url": "https://arxiv.org/abs/1706.03762",
        "title": "Attention Is All You Need",
        "quote": "The Transformer is based solely on attention mechanisms.",
        "snippet": "The Transformer is based solely on attention mechanisms.",
        "source_type": "paper",
        "quality_score": 1.0,
    }
    worker_result = AgentResult(
        task_id="task_1",
        status=AgentStatus.SUCCESS,
        output="Transformer is based on attention mechanisms.",
        sources=[source],
        confidence=0.8,
    )
    agent = SummarizerAgent(name="summarizer", policy=SynthesisPolicy())
    result = asyncio.run(
        agent.run(
            SubTask("synthesize", TaskType.ANALYZE, "Synthesize"),
            {"query": "Transformer", "results": [worker_result]},
        )
    )
    report = result.output
    assert report.claims
    assert report.claims[0]["citations"] == ["S1"]
    assert report.evidence_metrics["citation_coverage"] == 1.0


def test_researcher_falls_back_after_tool_failure() -> None:
    agent = ResearcherAgent(
        name="researcher",
        policy=FallbackPolicy(),
        tools=[FailingTool(), MockWebSearchTool(delay_ms=(0, 0))],
    )
    task = SubTask(
        task_id="task_fallback",
        task_type=TaskType.SEARCH,
        description="Research a Transformer paper",
    )
    result = asyncio.run(agent.run(task, {"query": task.description}))
    assert result.status == AgentStatus.SUCCESS
    assert result.sources
    assert any(step.get("error") for step in result.trajectory if step.get("role") == "tool")
