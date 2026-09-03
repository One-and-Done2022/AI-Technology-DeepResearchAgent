"""Claim-level metrics for AI technology research reports."""
from __future__ import annotations

import re
from typing import Any

from src.evidence.verifier import evidence_overlap


_ABSTENTION_MARKERS = (
    "证据不足",
    "无法验证",
    "无法确认",
    "insufficient evidence",
    "cannot verify",
    "unknown",
)
_PRIMARY_TYPES = {"paper", "official_doc", "official_repository", "institutional"}


def _get(report: Any, key: str, default: Any) -> Any:
    if isinstance(report, dict):
        return report.get(key, default)
    return getattr(report, key, default)


class ClaimMetrics:
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
        matched = sum(evidence_overlap(claim, content) >= 0.55 for claim in required_claims)
        return matched / len(required_claims)

    @staticmethod
    def source_metrics(sources: list[dict[str, Any]]) -> dict[str, float]:
        if not sources:
            return {
                "source_quality": 0.0,
                "primary_source_rate": 0.0,
                "source_url_syntax_validity": 0.0,
                "source_diversity": 0.0,
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
    def evidence_metrics(claims: list[dict[str, Any]]) -> dict[str, float]:
        total = len(claims)
        if not total:
            return {
                "citation_coverage": 0.0,
                "citation_entailment": 0.0,
                "unsupported_claim_rate": 1.0,
                "contradicted_claim_rate": 0.0,
            }
        cited = [claim for claim in claims if claim.get("citations")]
        supported = sum(claim.get("verification_status") == "supported" for claim in cited)
        partial = sum(claim.get("verification_status") == "partially_supported" for claim in cited)
        contradicted = sum(claim.get("verification_status") == "contradicted" for claim in claims)
        unsupported = sum(
            claim.get("verification_status") in {"unknown", "contradicted"} for claim in claims
        )
        return {
            "citation_coverage": len(cited) / total,
            "citation_entailment": (supported + 0.5 * partial) / len(cited) if cited else 0.0,
            "unsupported_claim_rate": unsupported / total,
            "contradicted_claim_rate": contradicted / total,
        }

    @staticmethod
    def abstention_accuracy(content: str, answerable: bool) -> float:
        abstained = any(marker in content.lower() for marker in _ABSTENTION_MARKERS)
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
        answerable: bool = True,
    ) -> dict[str, float]:
        content = str(_get(report, "content", ""))
        sources = list(_get(report, "sources", []))
        claims = list(_get(report, "claims", []))
        runtime = dict(_get(report, "runtime_metrics", {}))

        metrics = {
            "topic_coverage": cls.topic_coverage(content, expected_topics or []),
            "reference_claim_recall": cls.reference_claim_recall(content, required_claims or []),
            "abstention_accuracy": cls.abstention_accuracy(content, answerable),
            "system_success": float(bool(content.strip()) and "Research failed" not in content),
            "efficiency": cls.efficiency(runtime),
        }
        metrics.update(cls.source_metrics(sources))
        metrics.update(cls.evidence_metrics(claims))

        metrics["composite_score"] = (
            0.20 * metrics["reference_claim_recall"]
            + 0.20 * metrics["topic_coverage"]
            + 0.25 * metrics["citation_entailment"]
            + 0.10 * (1.0 - metrics["unsupported_claim_rate"])
            + 0.10 * metrics["source_quality"]
            + 0.05 * metrics["abstention_accuracy"]
            + 0.05 * metrics["system_success"]
            + 0.05 * metrics["efficiency"]
        )
        return {key: round(float(value), 6) for key, value in metrics.items()}
