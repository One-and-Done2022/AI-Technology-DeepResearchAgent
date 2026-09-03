from __future__ import annotations

from src.evidence.extractor import EvidencePipeline, extract_claims, normalize_sources
from src.evidence.schemas import Source
from src.evidence.store import EvidenceStore
from src.evidence.verifier import EvidenceVerifier


def test_normalize_sources_and_verify_cited_claim() -> None:
    trajectory = [
        {
            "role": "tool",
            "name": "web_search",
            "arguments": {"query": "PagedAttention"},
            "result": {
                "source": "mock",
                "results": [
                    {
                        "url": "https://example.org/paged-attention",
                        "title": "PagedAttention documentation",
                        "snippet": "PagedAttention manages the KV cache with paged memory blocks.",
                    }
                ],
            },
        }
    ]
    sources = normalize_sources(trajectory)
    assert len(sources) == 1
    assert sources[0].source_id == "S1"

    claims = extract_claims(
        "PagedAttention manages the KV cache with paged memory blocks [S1].",
        sources,
    )
    verified = EvidenceVerifier().verify_all(claims, sources)
    assert verified[0].verification_status.value == "supported"


def test_pipeline_marks_uncited_claim_unknown() -> None:
    pipeline = EvidencePipeline()
    sources = [
        Source(
            source_id="S1",
            url="https://arxiv.org/abs/2309.06180",
            title="A paper",
            quote="A documented architecture uses paged memory for KV cache management.",
            quality_score=1.0,
        ).to_dict()
    ]
    claims = pipeline.build_claims(
        "This system has exactly 999 percent higher throughput in every workload.",
        sources,
    )
    assert claims[0]["verification_status"] == "unknown"


def test_evidence_store_round_trip(tmp_path) -> None:
    store = EvidenceStore(str(tmp_path / "evidence.db"))
    source = Source(
        source_id="S1",
        url="https://github.com/example/project",
        title="example/project",
        quote="Official repository documentation.",
        quality_score=0.9,
    ).to_dict()
    store.save_report(
        run_id="run-1",
        query="test query",
        content="A report [S1].",
        sources=[source],
        claims=[{"claim_id": "C1", "statement": "A report", "citations": ["S1"]}],
        metrics={"citation_entailment": 1.0},
    )
    loaded = store.load_report("run-1")
    assert loaded is not None
    assert loaded["sources"][0]["source_id"] == "S1"
    assert loaded["metrics"]["citation_entailment"] == 1.0
