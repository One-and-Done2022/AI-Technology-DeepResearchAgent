"""Claim-level metrics for AI technology research reports."""
from __future__ import annotations

import re
from typing import Any

from src.evidence.verifier import evidence_overlap


_WHOLE_ANSWER_ABSTENTION_PATTERNS = (
    r"(?:整体|当前|因此|结论(?:是|为)?)[^。\n]{0,30}(?:无法回答|不能回答)",
    r"无法确认[^。\n]{0,60}(?:是否存在|真实性|该说法|这一说法)",
    r"(?:没有|未找到|缺乏)[^。\n]{0,40}(?:公开|官方|可靠)[^。\n]{0,30}(?:证据|资料|数据)",
    r"(?:insufficient evidence|cannot verify)[^.\n]{0,60}(?:exist|authentic|claim)",
)
_PRIMARY_TYPES = {"paper", "official_doc", "official_repository", "institutional"}


def _get(report: Any, key: str, default: Any) -> Any:
    if isinstance(report, dict):
        return report.get(key, default)
    return getattr(report, key, default)


class ClaimMetrics:
    @staticmethod
    def retrieval_metrics(
        sources: list[dict[str, Any]], gold_source_patterns: list[str]
    ) -> dict[str, float | None]:
        if not gold_source_patterns:
            return {"gold_source_recall_at_10": None, "gold_source_precision_at_10": None}
        urls = [str(source.get("url", "")).lower() for source in sources[:10]]
        patterns = [pattern.lower() for pattern in gold_source_patterns]
        matched_patterns = sum(any(pattern in url for url in urls) for pattern in patterns)
        matched_urls = sum(any(pattern in url for pattern in patterns) for url in urls)
        return {
            "gold_source_recall_at_10": matched_patterns / len(patterns),
            "gold_source_precision_at_10": matched_urls / len(urls) if urls else 0.0,
        }

    @staticmethod
    def topic_coverage(content: str, expected_topics: list[str]) -> float:
        if not expected_topics:
            return 1.0
        lowered = content.lower()
        covered = 0
        for topic in expected_topics:
            variants = [part.strip().lower() for part in topic.split("|") if part.strip()]
            if any(variant in lowered for variant in variants):
                covered += 1
        return covered / len(expected_topics)

    @staticmethod
    def reference_claim_recall(content: str, required_claims: list[str]) -> float:
        if not required_claims:
            return 1.0
        # Compare each reference claim with the best matching sentence rather
        # than with the whole report.  Whole-document overlap is length
        # biased: a long, otherwise correct report can receive zero recall
        # simply because unrelated sentences dilute the denominator.
        sentences = [
            sentence.strip()
            for sentence in re.split(r"[。！？!?；;\n]+|(?<=[.!?])\s+", content)
            if sentence.strip()
        ]
        if not sentences:
            sentences = [content]
        matched = sum(
            max(evidence_overlap(claim, sentence) for sentence in sentences) >= 0.55
            for claim in required_claims
        )
        return float(matched / len(required_claims))

    @staticmethod
    def source_metrics(sources: list[dict[str, Any]]) -> dict[str, float | None]:
        if not sources:
            return {
                "source_quality": None,
                "primary_source_rate": None,
                "source_url_syntax_validity": None,
                "source_diversity": None,
            }
        quality = sum(float(source.get("quality_score", 0.0)) for source in sources) / len(sources)
        primary = sum(source.get("source_type") in _PRIMARY_TYPES for source in sources) / len(sources)
        valid = sum(bool(re.match(r"https?://", str(source.get("url", "")))) for source in sources) / len(sources)
        hosts = {
            re.sub(r"^www\.", "", match.group(1).lower())
            for source in sources
            if (match := re.match(r"https?://([^/]+)", str(source.get("url", ""))))
        }
        diversity = min(1.0, len(hosts) / 3)
        return {
            "source_quality": quality,
            "primary_source_rate": primary,
            "source_url_syntax_validity": valid,
            "source_diversity": diversity,
        }

    @staticmethod
    def evidence_metrics(
        claims: list[dict[str, Any]], applicable: bool
    ) -> dict[str, float | None]:
        if not applicable:
            return {
                "citation_coverage": None,
                "citation_entailment": None,
                "unsupported_claim_rate": None,
                "contradicted_claim_rate": None,
                "citation_completeness": None,
                "unsupported_important_claim_rate": None,
            }
        verifiable = [
            claim for claim in claims
            if claim.get("metadata", {}).get(
                "is_verifiable", claim.get("claim_type") != "recommendation"
            )
        ]
        total = len(verifiable)
        if not total:
            return {
                "citation_coverage": 0.0,
                "citation_entailment": 0.0,
                "unsupported_claim_rate": 1.0,
                "contradicted_claim_rate": 0.0,
                "citation_completeness": 0.0,
                "unsupported_important_claim_rate": 0.0,
            }
        cited = [claim for claim in verifiable if claim.get("citations")]
        supported = sum(claim.get("verification_status") == "supported" for claim in cited)
        partial = sum(claim.get("verification_status") == "partially_supported" for claim in cited)
        contradicted = sum(claim.get("verification_status") == "contradicted" for claim in verifiable)
        unsupported = sum(
            claim.get("verification_status") in {"unknown", "contradicted"} for claim in verifiable
        )
        important = [claim for claim in verifiable if claim.get("importance") == "high"]
        unsupported_important = sum(
            claim.get("verification_status") in {"unknown", "contradicted"} for claim in important
        )
        return {
            "citation_coverage": len(cited) / total,
            "citation_entailment": (supported + 0.5 * partial) / len(cited) if cited else 0.0,
            "unsupported_claim_rate": unsupported / total,
            "contradicted_claim_rate": contradicted / total,
            "citation_completeness": len(cited) / total,
            "unsupported_important_claim_rate": (
                unsupported_important / len(important) if important else 0.0
            ),
        }

    @staticmethod
    def answerability_decision(content: str) -> str:
        normalized = content.lower()
        abstained = any(
            re.search(pattern, normalized, flags=re.I)
            for pattern in _WHOLE_ANSWER_ABSTENTION_PATTERNS
        )
        return "abstained" if abstained else "answered"

    @classmethod
    def abstention_accuracy(cls, content: str, answerable: bool) -> float:
        abstained = cls.answerability_decision(content) == "abstained"
        return float((answerable and not abstained) or (not answerable and abstained))

    @staticmethod
    def efficiency(runtime: dict[str, Any], latency_budget: float = 180.0, tool_budget: int = 30) -> float:
        latency = float(runtime.get("elapsed_seconds", 0.0))
        tool_calls = int(runtime.get("tool_calls", 0))
        if latency <= 0:
            latency_score = 0.0
        else:
            latency_score = min(1.0, latency_budget / latency)
        tool_score = min(1.0, tool_budget / max(tool_calls, 1))
        return (latency_score + tool_score) / 2

    @classmethod
    def evaluate(
        cls,
        report: Any,
        expected_topics: list[str] | None = None,
        required_claims: list[str] | None = None,
        gold_source_patterns: list[str] | None = None,
        answerable: bool = True,
    ) -> dict[str, float | None]:
        content = str(_get(report, "content", ""))
        sources = list(_get(report, "sources", []))
        claims = list(_get(report, "claims", []))
        runtime = dict(_get(report, "runtime_metrics", {}))
        evidence_applicable = bool(_get(report, "verification_applicability", bool(sources)))

        metrics: dict[str, float | None] = {
            "topic_coverage": cls.topic_coverage(content, expected_topics or []),
            "reference_claim_recall": cls.reference_claim_recall(content, required_claims or []),
            "abstention_accuracy": cls.abstention_accuracy(content, answerable),
            "system_success": float(bool(content.strip()) and "Research failed" not in content),
            "efficiency": cls.efficiency(runtime),
        }
        metrics.update(cls.source_metrics(sources))
        metrics.update(cls.retrieval_metrics(sources, gold_source_patterns or []))
        metrics.update(cls.evidence_metrics(claims, evidence_applicable))

        # Content quality must not reward a faster report.  Efficiency is
        # reported separately so that a latency improvement cannot be
        # mistaken for a factual or coverage improvement.
        metrics["content_quality_score"] = 10.0 * (
            0.40 * float(metrics["reference_claim_recall"] or 0.0)
            + 0.35 * float(metrics["topic_coverage"] or 0.0)
            + 0.15 * float(metrics["abstention_accuracy"] or 0.0)
            + 0.10 * float(metrics["system_success"] or 0.0)
        )
        # Keep the historical name for consumers written before the split.
        metrics["content_score"] = metrics["content_quality_score"]
        return {
            key: round(float(value), 6) if value is not None else None
            for key, value in metrics.items()
        }
