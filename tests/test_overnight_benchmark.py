from __future__ import annotations

from evaluation.judge import DeepSeekJudge, JudgeResponse, parse_json_object, summarize_claim_judgments
from evaluation.metrics.claim_metrics import ClaimMetrics
from scripts.run_tech_benchmark import (
    AdaptiveLimiter,
    SYSTEMS,
    _config_for_system,
    _load_records,
    _record_complete,
    _report_failure,
    render_report,
    write_report_comparison,
    _upsert_record,
    evaluate_records,
)
from src.evidence.extractor import EvidencePipeline, extract_claims
from src.evidence.schemas import Source
from src.models.vllm_policy import VLLMPolicy, _GLOBAL_REQUEST_LIMITER, configure_global_request_limiter
from evaluation.metrics.stats import bootstrap_ci_paired


def test_four_system_capabilities_are_isolated() -> None:
    base = {"model": {}, "evidence": {"enabled": True}, "research": {"enabled": True}}
    configs = {system: _config_for_system(base, system) for system in SYSTEMS}
    assert configs["direct_llm"]["research"]["enabled"] is False
    assert configs["search_agent"]["evidence"]["verification_enabled"] is False
    assert configs["evidence_agent"]["research"]["max_rounds"] == 1
    assert configs["full_iterresearch"]["research"]["enabled"] is True
    assert configs["full_stack"]["quality_control"]["adversarial_enabled"] is True
    assert configs["full_stack"]["quality_control"]["compression_enabled"] is True
    assert configs["full_stack"]["quality_control"]["memory_enabled"] is True
    assert configs["full_stack"]["evidence"]["verification_enabled"] is True
    assert all(config["evidence"]["enabled"] is False for config in configs.values())
    assert all(config["model"]["backend_sampling"]["qwen"]["strict_errors"] for config in configs.values())


def test_full_stack_ablation_switches_disable_only_the_target_module() -> None:
    base = {"model": {}, "evidence": {"enabled": True}, "research": {"enabled": True}}
    no_redblue = _config_for_system(base, "full_stack_without_redblue")
    no_compressor = _config_for_system(base, "full_stack_without_compressor")
    no_memory = _config_for_system(base, "full_stack_without_memory")
    for config in (no_redblue, no_compressor, no_memory):
        assert config["evidence"]["verification_enabled"] is True
        assert config["research"]["enabled"] is True
    assert no_redblue["quality_control"]["adversarial_enabled"] is False
    assert no_redblue["quality_control"]["compression_enabled"] is True
    assert no_redblue["quality_control"]["memory_enabled"] is True
    assert no_compressor["quality_control"]["adversarial_enabled"] is True
    assert no_compressor["quality_control"]["compression_enabled"] is False
    assert no_memory["quality_control"]["memory_enabled"] is False


def test_claims_are_atomic_typed_and_can_skip_verification() -> None:
    source = Source(source_id="S1", url="https://example.org", quote="PagedAttention manages KV cache.")
    claims = extract_claims("vLLM 使用 PagedAttention 管理 KV Cache，并通过连续批处理提高吞吐 [S1]。", [source])
    assert len(claims) == 2
    assert all(claim.claim_type.value in {"mechanism", "performance"} for claim in claims)
    raw = EvidencePipeline(verify=False).build_claims("PagedAttention manages KV cache [S1].", [source.to_dict()])
    assert raw[0]["verification_status"] == "unknown"


def test_claim_extractor_ignores_markdown_scaffolding() -> None:
    claims = extract_claims(
        "# 标题\n| 项目 | 结论 |\n|---|---|\nTransformer 使用注意力机制。",
        [],
    )
    assert [claim.statement for claim in claims] == ["Transformer 使用注意力机制。"]


def test_verified_pipeline_conservatively_binds_matching_evidence() -> None:
    source = Source(
        source_id="S1",
        url="https://example.org",
        quote="PagedAttention manages KV cache using paged memory blocks.",
    )
    claims = EvidencePipeline(verify=True).build_claims(
        "PagedAttention manages KV cache using paged memory blocks.",
        [source.to_dict()],
    )
    assert claims[0]["citations"] == ["S1"]
    assert claims[0]["metadata"]["citation_binding"] == "lexical_candidate"
    assert claims[0]["verification_status"] == "supported"


def test_unverified_pipeline_keeps_candidate_citations() -> None:
    source = Source(
        source_id="S1",
        url="https://example.org",
        quote="PagedAttention manages KV cache using paged memory blocks.",
    )
    claims = EvidencePipeline(verify=False).build_claims(
        "PagedAttention manages KV cache using paged memory blocks.",
        [source.to_dict()],
    )
    assert claims[0]["citations"] == ["S1"]
    assert claims[0]["verification_status"] == "unknown"


def test_candidate_binding_can_use_source_title_without_claiming_support() -> None:
    source = Source(
        source_id="S1",
        url="https://example.org/attention",
        title="Attention Is All You Need",
        quote="A sentence about optimization.",
    )
    claims = EvidencePipeline(verify=True).build_claims(
        "Attention Is All You Need introduces the Transformer architecture.",
        [source.to_dict()],
    )
    assert claims[0]["citations"] == ["S1"]
    assert claims[0]["metadata"]["binding_field"] == "title"
    assert claims[0]["verification_status"] == "unknown"


def test_bound_citations_are_visible_in_report_without_changing_status() -> None:
    source = Source(
        source_id="S1",
        url="https://example.org",
        title="Attention Is All You Need",
        quote="Attention mechanisms are used in the Transformer.",
    )
    pipeline = EvidencePipeline(verify=True)
    claims = pipeline.build_claims(
        "Attention Is All You Need introduces the Transformer architecture.",
        [source.to_dict()],
    )
    annotated = pipeline.annotate_citations(
        "Attention Is All You Need introduces the Transformer architecture.",
        claims,
    )
    assert "[S1]" in annotated
    assert claims[0]["verification_status"] in {"unknown", "partially_supported", "supported"}


def test_evidence_metrics_are_null_when_not_applicable() -> None:
    report = {"content": "A sufficiently long atomic technical claim without a source.",
              "claims": [], "sources": [], "verification_applicability": False,
              "runtime_metrics": {"elapsed_seconds": 1, "tool_calls": 0}}
    metrics = ClaimMetrics.evaluate(report)
    assert metrics["citation_entailment"] is None
    assert metrics["unsupported_claim_rate"] is None
    assert metrics["content_score"] >= 0


def test_partial_global_timeout_is_not_a_success() -> None:
    assert _report_failure({
        "content": "部分报告",
        "runtime_metrics": {"partial": True, "termination_reason": "global_timeout"},
    }).startswith("ResearchRunPartial:")


def test_single_pair_is_descriptive_not_significant() -> None:
    result = bootstrap_ci_paired([1.0])
    assert result["insufficient_n"] is True
    assert result["significant"] is False


def test_partial_records_are_excluded_from_quality_aggregates() -> None:
    class Bench:
        def evaluate_report(self, report, case_id):
            return {"metrics": {"system_success": 1.0, "content_score": 9.0,
                                 "topic_coverage": 1.0, "reference_claim_recall": 1.0,
                                 "abstention_accuracy": 1.0, "efficiency": 1.0,
                                 "source_quality": None, "primary_source_rate": None,
                                 "source_diversity": None, "gold_source_recall_at_10": None,
                                 "gold_source_precision_at_10": None}}

    valid = {"record_key": "valid", "case_id": "c1", "system": "direct_llm",
             "report": {"runtime_metrics": {"wall_seconds": 2}},
             "report_judge": {"content_score": 8.0, "factual_accuracy": 8.0,
                              "comprehensiveness": 8.0, "analysis_quality": 8.0,
                              "presentation": 8.0, "instruction_following": 8.0},
             "cost": {}}
    partial = {"record_key": "partial", "case_id": "c2", "system": "direct_llm",
               "error": "ResearchRunPartial: global_timeout",
               "report": {"runtime_metrics": {"wall_seconds": 20}},
               "report_judge": {"content_score": 1.0, "factual_accuracy": 1.0,
                                "comprehensiveness": 1.0, "analysis_quality": 1.0,
                                "presentation": 1.0, "instruction_following": 1.0},
               "cost": {}}
    summary = evaluate_records(Bench(), [valid, partial])
    assert summary["systems"]["direct_llm"]["success_rate"] == 0.5
    assert summary["systems"]["direct_llm"]["judge_content_score"]["mean"] == 8.0


def test_judge_json_and_external_claim_summary() -> None:
    parsed = parse_json_object("<think>hidden</think>```json\n{\"status\":\"supported\"}\n```")
    assert parsed["status"] == "supported"
    metrics = summarize_claim_judgments(
        [{"citations": ["S1"]}, {"citations": []}],
        [{"status": "supported"}, {"status": "unknown"}],
    )
    assert metrics["citation_correctness"] == 1.0
    assert metrics["unsupported_claim_rate"] == 0.5


def test_external_summary_ignores_non_verifiable_recommendations() -> None:
    metrics = summarize_claim_judgments(
        [
            {"claim_id": "C1", "claim_type": "recommendation", "citations": []},
            {"claim_id": "C2", "claim_type": "performance", "citations": ["S1"], "importance": "high"},
        ],
        [{"claim_id": "C2", "status": "supported"}],
    )
    assert metrics["citation_correctness"] == 1.0
    assert metrics["unsupported_important_claim_rate"] == 0.0


def test_judge_retries_invalid_json(monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "k")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL", "judge")
    judge = DeepSeekJudge(max_retries=1)

    class Message:
        def __init__(self, content):
            self.content = content

    class Usage:
        prompt_tokens = 1
        completion_tokens = 1
        total_tokens = 2

    class Completion:
        usage = Usage()
        def __init__(self, content):
            self.choices = [type("Choice", (), {"message": Message(content)})]

    class Completions:
        def __init__(self):
            self.calls = 0
        def create(self, **kwargs):
            self.calls += 1
            return Completion("not json" if self.calls == 1 else '{"ok": true}')

    completions = Completions()
    judge.client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    result = judge._request("system", "user")
    assert result.value == {"ok": True}
    assert completions.calls == 2


def test_policy_usage_is_real_when_provider_returns_usage() -> None:
    class Usage:
        prompt_tokens = 7
        completion_tokens = 3
        total_tokens = 10

    class Message:
        content = "ok"
        tool_calls = []
        reasoning_content = None

    class Completion:
        choices = [type("Choice", (), {"message": Message()})]
        usage = Usage()

    policy = VLLMPolicy(timeout=1.0)
    policy.client = type("Client", (), {"chat": type("Chat", (), {
        "completions": type("Completions", (), {"create": lambda self, **kwargs: Completion()})()
    })()})()
    result = policy([{"role": "user", "content": "test"}])
    assert result["usage"] == {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10,
                               "usage_estimated": False}


def test_adaptive_limiter_halves_to_one() -> None:
    import asyncio

    limiter = AdaptiveLimiter(8)
    asyncio.run(limiter.halve())
    asyncio.run(limiter.halve())
    asyncio.run(limiter.halve())
    asyncio.run(limiter.halve())
    assert limiter.limit == 1


def test_qwen_global_limiter_configuration_and_429_backoff() -> None:
    configure_global_request_limiter(concurrency=12, rpm=600)
    assert _GLOBAL_REQUEST_LIMITER.snapshot() == {
        "limit": 12, "maximum": 12, "rpm": 600, "active": 0,
    }
    _GLOBAL_REQUEST_LIMITER.on_429()
    assert _GLOBAL_REQUEST_LIMITER.snapshot()["limit"] == 6
    _GLOBAL_REQUEST_LIMITER.on_429()
    assert _GLOBAL_REQUEST_LIMITER.snapshot()["limit"] == 3


def test_qwen_limiter_can_start_below_recovery_ceiling() -> None:
    configure_global_request_limiter(concurrency=12, rpm=600, initial_concurrency=3)
    snapshot = _GLOBAL_REQUEST_LIMITER.snapshot()
    assert snapshot["limit"] == 3
    assert snapshot["maximum"] == 12


def test_jsonl_upsert_keeps_resume_key_unique(tmp_path) -> None:
    path = tmp_path / "results.jsonl"
    _upsert_record(path, {"record_key": "case:system:model:config", "error": "first"})
    _upsert_record(path, {"record_key": "case:system:model:config", "error": ""})
    records = _load_records(path)
    assert len(records) == 1
    assert records[0]["error"] == ""


def test_failed_report_is_not_treated_as_resumable_success() -> None:
    report = {"content": "Research failed due to persistent errors or global timeout."}
    record = {"error": "", "report": report, "report_judge": {"content_score": 1.0}}
    assert _report_failure(report).startswith("ResearchRunFailed:")
    assert _record_complete(record, judge_enabled=True) is False


def test_successful_judged_report_is_complete() -> None:
    record = {
        "error": "",
        "report": {"content": "A complete technical report."},
        "report_judge": {"content_score": 8.0},
    }
    assert _record_complete(record, judge_enabled=True) is True


def test_report_exposes_objective_metrics_and_negative_direction() -> None:
    summary = {
        "systems": {
            "direct_llm": {
                "runs": 1,
                "success_rate": 1.0,
                "content_score": {"mean": 5.0},
                "latency_seconds": {"p95": 1.0},
                "judge_tokens": 2,
                "average_cost_cny": None,
                "objective": {
                    "topic_coverage": {"mean": 0.8},
                    "reference_claim_recall": {"mean": 0.7},
                    "abstention_accuracy": {"mean": 1.0},
                },
                "source": {},
                "evidence": {},
            }
        },
        "paired_comparisons": {
            "search_minus_direct": {
                "mean_diff": -1.0, "ci_lower": -2.0, "ci_upper": -0.1,
                "cohens_dz": -0.5,
            }
        },
    }
    report = render_report(summary)
    assert "## 客观指标" in report
    assert "显著下降" in report


def test_summary_keeps_judge_and_rule_content_separate() -> None:
    from scripts.run_tech_benchmark import evaluate_records

    class Bench:
        def evaluate_report(self, report, case_id):
            return {"metrics": {
                "content_score": 7.0, "system_success": 1.0,
                "topic_coverage": 1.0, "reference_claim_recall": 1.0,
                "abstention_accuracy": 1.0, "efficiency": 1.0,
                "source_quality": None, "primary_source_rate": None,
                "source_diversity": None, "gold_source_recall_at_10": None,
                "gold_source_precision_at_10": None,
            }}

    records = [
        {"record_key": "a", "case_id": "a", "system": "direct_llm",
         "report": {"runtime_metrics": {"wall_seconds": 1}},
         "report_judge": {"content_score": 5.0, "factual_accuracy": 5.0,
                          "comprehensiveness": 5.0, "analysis_quality": 5.0,
                          "presentation": 5.0, "instruction_following": 5.0}, "cost": {}},
        {"record_key": "b", "case_id": "b", "system": "search_agent",
         "report": {"runtime_metrics": {"wall_seconds": 1}},
         "report_judge": {"content_score": 4.0, "factual_accuracy": 4.0,
                          "comprehensiveness": 4.0, "analysis_quality": 4.0,
                          "presentation": 4.0, "instruction_following": 4.0}, "cost": {}},
    ]
    summary = evaluate_records(Bench(), records)
    assert summary["systems"]["direct_llm"]["judge_content_score"]["mean"] == 5.0
    assert summary["systems"]["direct_llm"]["rule_content_score"]["mean"] == 7.0


def test_summary_aggregates_runtime_quality_control_metrics() -> None:
    from scripts.run_tech_benchmark import evaluate_records

    class Bench:
        def evaluate_report(self, report, case_id):
            return {"metrics": {
                "content_score": 7.0, "system_success": 1.0,
                "topic_coverage": 1.0, "reference_claim_recall": 1.0,
                "abstention_accuracy": 1.0, "efficiency": 1.0,
                "source_quality": None, "primary_source_rate": None,
                "source_diversity": None, "gold_source_recall_at_10": None,
                "gold_source_precision_at_10": None,
            }}

    record = {
        "record_key": "full", "case_id": "full", "system": "full_stack",
        "report": {"runtime_metrics": {
            "wall_seconds": 3, "red_issue_count": 4,
            "blue_fix_acceptance_rate": 0.75, "audit_score": 0.5,
            "deleted_claim_count": 1, "oscillation_count": 0,
            "adversarial_rounds": 2, "compression_ratio": 0.6,
            "evidence_retention": 0.95, "memory_added": 3,
            "memory_deduplicated": 1, "memory_size": 3,
        }},
        "report_judge": {"content_score": 7.0, "factual_accuracy": 7.0,
                          "comprehensiveness": 7.0, "analysis_quality": 7.0,
                          "presentation": 7.0, "instruction_following": 7.0},
        "cost": {},
    }
    summary = evaluate_records(Bench(), [record])
    metrics = summary["systems"]["full_stack"]
    assert metrics["adversarial"]["red_issue_count"]["mean"] == 4.0
    assert metrics["compression"]["evidence_retention"]["mean"] == 0.95
    assert metrics["memory"]["memory_deduplicated"]["mean"] == 1.0


def test_report_comparison_package_contains_all_artifacts(tmp_path) -> None:
    bench = type("Bench", (), {
        "get_case": lambda self, case_id: {
            "id": case_id, "query": "问题", "as_of": "2026-09-18",
            "answerable": True, "expected_topics": ["主题"],
            "required_claims": [], "gold_source_patterns": [],
        }
    })()
    records = [
        {"case_id": "aiml_001", "system": system,
         "report": {"content": f"{system} report", "sources": [], "claims": []},
         "evaluation": {"metrics": {"system_success": 1.0, "content_score": 7.0}},
         "report_judge": {"content_score": 6.0, "reason": "ok"},
         "external_evidence_metrics": None}
        for system in SYSTEMS
    ]
    write_report_comparison(records, bench, tmp_path)
    assert (tmp_path / "README.md").exists()
    assert (tmp_path / "aiml_001" / "direct_llm.md").read_text()
    assert (tmp_path / "aiml_001" / "comparison.md").exists()
