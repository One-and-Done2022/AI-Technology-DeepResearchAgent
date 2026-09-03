from __future__ import annotations

from evaluation.benchmarks.tech_research_bench import TechResearchBench
from evaluation.metrics.claim_metrics import ClaimMetrics


def _supported_report() -> dict:
    return {
        "content": (
            "标准全局自注意力相对于序列长度具有平方级复杂度 [S1]。"
            "自注意力使用 QKV，并且长序列会增加计算与存储开销 [S1]。"
        ),
        "sources": [
            {
                "source_id": "S1",
                "url": "https://arxiv.org/abs/1706.03762",
                "source_type": "paper",
                "quality_score": 1.0,
            }
        ],
        "claims": [
            {
                "claim_id": "C1",
                "statement": "标准全局自注意力相对于序列长度具有平方级复杂度",
                "citations": ["S1"],
                "verification_status": "supported",
            }
        ],
        "runtime_metrics": {"elapsed_seconds": 60, "tool_calls": 4},
    }


def test_dataset_has_balanced_30_cases() -> None:
    bench = TechResearchBench()
    assert len(bench.cases) == 30
    counts = {}
    for case in bench.cases:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert set(counts.values()) == {6}


def test_claim_metrics_reward_supported_evidence() -> None:
    metrics = ClaimMetrics.evaluate(
        _supported_report(),
        expected_topics=["自注意力", "QKV", "复杂度", "长序列"],
        required_claims=["标准全局自注意力相对于序列长度具有平方级计算或存储开销"],
    )
    assert metrics["citation_entailment"] == 1.0
    assert metrics["unsupported_claim_rate"] == 0.0
    assert metrics["source_quality"] == 1.0
    assert metrics["composite_score"] > 0.8


def test_benchmark_scores_structured_report() -> None:
    result = TechResearchBench().evaluate_report(_supported_report(), "aiml_001")
    assert result["case_id"] == "aiml_001"
    assert result["metrics"]["system_success"] == 1.0
