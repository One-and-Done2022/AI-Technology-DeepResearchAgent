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
        gold_source_patterns=["arxiv.org/abs/1706.03762"],
    )
    assert metrics["citation_entailment"] == 1.0
    assert metrics["unsupported_claim_rate"] == 0.0
    assert metrics["source_quality"] == 1.0
    assert metrics["gold_source_recall_at_10"] == 1.0
    assert metrics["content_score"] > 8.0
    assert metrics["content_quality_score"] == metrics["content_score"]


def test_content_quality_score_is_independent_of_efficiency() -> None:
    report = {
        "content": "标准全局自注意力相对于序列长度具有平方级复杂度。",
        "runtime_metrics": {"elapsed_seconds": 1, "tool_calls": 1},
    }
    fast = ClaimMetrics.evaluate(report, required_claims=["标准全局自注意力相对于序列长度具有平方级计算或存储开销"])
    report["runtime_metrics"] = {"elapsed_seconds": 9999, "tool_calls": 1000}
    slow = ClaimMetrics.evaluate(report, required_claims=["标准全局自注意力相对于序列长度具有平方级计算或存储开销"])
    assert fast["content_quality_score"] == slow["content_quality_score"]
    assert fast["efficiency"] > slow["efficiency"]


def test_reference_claim_recall_uses_best_sentence_not_whole_document() -> None:
    content = (
        "标准全局自注意力相对于序列长度具有平方级复杂度。"
        "这是一个与目标 Claim 无关的长段落，用于模拟报告中的其他分析内容。"
    )
    metrics = ClaimMetrics.evaluate(
        {"content": content, "runtime_metrics": {"elapsed_seconds": 30, "tool_calls": 1}},
        required_claims=["标准全局自注意力相对于序列长度具有平方级计算或存储开销"],
    )
    assert metrics["reference_claim_recall"] == 1.0


def test_local_uncertainty_is_not_whole_answer_abstention() -> None:
    content = "vLLM 适合在线推理。限制：部分硬件指标证据不足。"
    assert ClaimMetrics.answerability_decision(content) == "answered"
    assert ClaimMetrics.abstention_accuracy(content, answerable=True) == 1.0


def test_whole_answer_abstention_detects_unverifiable_entity() -> None:
    content = "结论：无法确认 HyperQuantumLM-900B 是否存在公开官方证据。"
    assert ClaimMetrics.answerability_decision(content) == "abstained"
    assert ClaimMetrics.abstention_accuracy(content, answerable=False) == 1.0


def test_benchmark_scores_structured_report() -> None:
    result = TechResearchBench().evaluate_report(_supported_report(), "aiml_001")
    assert result["case_id"] == "aiml_001"
    assert result["metrics"]["system_success"] == 1.0
