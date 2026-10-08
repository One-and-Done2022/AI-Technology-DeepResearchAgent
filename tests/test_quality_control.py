from src.adversarial import LLMRedBlueAuditor, RedBlueAuditor
from src.compressor import EvidencePreservingCompressor
from src.memory import EvidenceMemory


def test_red_blue_audit_marks_unsupported_claims_without_inventing_evidence() -> None:
    result = RedBlueAuditor(max_rounds=2).audit(
        "报告正文",
        [
            {
                "claim_id": "C1",
                "statement": "系统支持某能力",
                "citations": ["S1"],
                "verification_status": "unknown",
                "metadata": {"is_verifiable": True},
            }
        ],
    )
    assert result.issues[0].action == "VERIFY"
    assert result.claims[0]["verification_status"] == "unknown"
    assert "Evidence Audit" in result.content
    assert result.metrics()["blue_fix_acceptance_rate"] == 0.0


def test_red_blue_can_keep_audit_log_out_of_user_report() -> None:
    result = RedBlueAuditor(max_rounds=1, expose_audit=False).audit(
        "报告正文",
        [{
            "claim_id": "C1",
            "statement": "系统支持某能力",
            "citations": [],
            "verification_status": "unknown",
            "metadata": {"is_verifiable": True},
        }],
    )
    assert "Evidence Audit" not in result.content
    assert result.issues[0].action == "VERIFY"


def test_red_blue_does_not_destroy_short_report_structure() -> None:
    result = RedBlueAuditor().audit(
        "### Key Findings\n- Transformer\n",
        [{
            "claim_id": "C1",
            "statement": "Transformer",
            "citations": [],
            "verification_status": "unknown",
            "metadata": {"is_verifiable": True},
        }],
    )
    assert "### Key Findings" in result.content
    assert "- Transformer" in result.content


def test_red_blue_keeps_uncited_claim_and_marks_verify() -> None:
    statement = "PagedAttention 通过分页方式管理推理过程中的 KV Cache。"
    result = RedBlueAuditor().audit(
        statement,
        [{
            "claim_id": "C1",
            "statement": statement,
            "citations": [],
            "verification_status": "unknown",
            "importance": "high",
            "metadata": {"is_verifiable": True},
        }],
    )
    assert statement in result.content
    assert result.deleted_claim_ids == []
    assert result.issues[0].action == "VERIFY"
    assert result.issues[0].severity == "high"


def test_red_blue_adds_coverage_issue_for_nonempty_report_without_claims() -> None:
    result = RedBlueAuditor(max_rounds=1).audit("只有报告文本，没有可解析的原子结论。", [])
    assert result.issues[0].action == "ADD"
    assert result.issues[0].dimension == "coverage"
    assert result.issues[0].resolved is True
    assert "claim extraction pass" in result.content
    assert result.metrics()["audit_score"] == 0.0


def test_llm_red_blue_uses_json_fallback_and_records_dimensions() -> None:
    class FakePolicy:
        def __init__(self) -> None:
            self.responses = [
                "```json\n"
                '{"dimensions":{"factual_accuracy":7,"logical_consistency":8,"citation_quality":4,"numeric_consistency":8,"coverage":6},'
                '"issues":[{"claim_id":"C1","dimension":"citation","action":"VERIFY","severity":"high","reason":"missing entailment"}]}\n```',
                'json: {"content":"报告正文 [S1]。", "operations":[{"claim_id":"C1","action":"VERIFY","resolved":true}]}',
            ]

        def __call__(self, messages):
            return {"content": self.responses.pop(0)}

    result = LLMRedBlueAuditor(FakePolicy(), max_rounds=1).audit(
        "报告正文 [S1]。",
        [{
            "claim_id": "C1",
            "statement": "报告正文",
            "citations": ["S1"],
            "verification_status": "unknown",
            "metadata": {"is_verifiable": True},
        }],
        query="测试问题",
        sources=[{"source_id": "S1", "title": "来源", "quote": "证据"}],
    )
    metrics = result.metrics()
    assert result.issues[0].dimension == "citation"
    assert result.issues[0].resolved is True
    assert metrics["json_parse_success_rate"] == 1.0
    assert metrics["json_parse_attempts"] == 2
    assert metrics["json_parse_strategies"]["plain_or_fenced"] == 1
    assert metrics["json_parse_strategies"]["balanced_object"] == 1


def test_llm_red_blue_falls_back_to_deterministic_audit_on_invalid_json() -> None:
    class InvalidPolicy:
        def __call__(self, messages):
            return {"content": "not json"}

    result = LLMRedBlueAuditor(InvalidPolicy(), max_rounds=1).audit(
        "没有引用的技术结论。",
        [{
            "claim_id": "C1",
            "statement": "没有引用的技术结论。",
            "citations": [],
            "verification_status": "unknown",
            "metadata": {"is_verifiable": True},
        }],
    )
    assert result.metrics()["llm_audit_fallback"] is True
    assert result.issues[0].action == "VERIFY"


def test_compressor_preserves_citation_sentences_and_reports_reduction() -> None:
    text = (
        "背景说明。\n"
        "vLLM 使用 PagedAttention 管理 KV Cache。[S1]\n"
        "这是一段可以被筛掉的重复说明。\n"
        "官方文档记录了该机制。[S2]"
    )
    result = EvidencePreservingCompressor().compress(
        text,
        claims=[{"claim_id": "C1", "statement": "vLLM 使用 PagedAttention"}],
        max_chars=80,
    )
    assert "[S1]" in result.text
    assert "[S2]" in result.text
    assert result.metrics()["compression_ratio"] >= 0


def test_evidence_memory_deduplicates_and_retrieves_sources() -> None:
    memory = EvidenceMemory()
    source = {"url": "https://example.org", "title": "PagedAttention", "quote": "KV Cache"}
    first = memory.add_sources([source])
    second = memory.add_sources([source])
    assert first["memory_added"] == 1
    assert second["memory_deduplicated"] == 1
    assert memory.search("PagedAttention", top_k=1)[0]["url"] == source["url"]
