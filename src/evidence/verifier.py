"""Claim-to-evidence verification with a deterministic offline fallback."""
from __future__ import annotations

import re
from typing import Iterable

from .schemas import Claim, EvidenceSpan, Source, VerificationStatus


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.+/-]*|\d+(?:\.\d+)?%?")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?%?")


def _tokens(text: str) -> set[str]:
    lowered = text.lower()
    tokens = {token for token in _WORD_RE.findall(lowered) if len(token) > 1}
    cjk = "".join(_CJK_RE.findall(lowered))
    tokens.update(cjk[i : i + 2] for i in range(max(0, len(cjk) - 1)))
    return tokens


def evidence_overlap(claim: str, quote: str) -> float:
    claim_tokens = _tokens(claim)
    if not claim_tokens:
        return 0.0
    quote_tokens = _tokens(quote)
    return len(claim_tokens & quote_tokens) / len(claim_tokens)


class EvidenceVerifier:
    """Verifies citations without requiring another model call.

    The deterministic verifier is intentionally conservative. It checks lexical
    support and numeric consistency and exposes `unknown` rather than inventing
    support. A calibrated LLM/NLI verifier can replace it later without changing
    the report schema.
    """

    def __init__(self, support_threshold: float = 0.22, partial_threshold: float = 0.08) -> None:
        self.support_threshold = support_threshold
        self.partial_threshold = partial_threshold

    def verify(self, claim: Claim, sources: Iterable[Source]) -> Claim:
        source_map = {source.source_id: source for source in sources}
        spans: list[EvidenceSpan] = []
        best_overlap = 0.0
        numeric_conflict = False
        claim_numbers = set(_NUMBER_RE.findall(claim.statement))

        for citation in claim.citations:
            source = source_map.get(citation)
            if source is None:
                continue
            overlap = evidence_overlap(claim.statement, source.quote)
            source_numbers = set(_NUMBER_RE.findall(source.quote))
            if claim_numbers and not claim_numbers.issubset(source_numbers):
                numeric_conflict = numeric_conflict or (
                    bool(source_numbers) and overlap >= self.partial_threshold
                )
            spans.append(
                EvidenceSpan(
                    source_id=source.source_id,
                    quote=source.quote,
                    locator=source.url,
                    overlap_score=round(overlap, 3),
                )
            )
            best_overlap = max(best_overlap, overlap)

        claim.evidence = spans
        if not spans:
            claim.verification_status = VerificationStatus.UNKNOWN
            claim.confidence = 0.0
        elif numeric_conflict:
            claim.verification_status = VerificationStatus.CONTRADICTED
            claim.confidence = round(min(1.0, best_overlap), 3)
        elif best_overlap >= self.support_threshold:
            claim.verification_status = VerificationStatus.SUPPORTED
            claim.confidence = round(min(1.0, 0.5 + best_overlap / 2), 3)
        elif best_overlap >= self.partial_threshold:
            claim.verification_status = VerificationStatus.PARTIALLY_SUPPORTED
            claim.confidence = round(best_overlap, 3)
        else:
            claim.verification_status = VerificationStatus.UNKNOWN
            claim.confidence = round(best_overlap, 3)
        return claim

    def verify_all(self, claims: list[Claim], sources: list[Source]) -> list[Claim]:
        return [self.verify(claim, sources) for claim in claims]

    @staticmethod
    def summarize(claims: list[Claim]) -> dict[str, float | int]:
        total = len(claims)
        cited = sum(bool(claim.citations) for claim in claims)
        supported = sum(
            claim.verification_status == VerificationStatus.SUPPORTED for claim in claims
        )
        partial = sum(
            claim.verification_status == VerificationStatus.PARTIALLY_SUPPORTED for claim in claims
        )
        contradicted = sum(
            claim.verification_status == VerificationStatus.CONTRADICTED for claim in claims
        )
        unknown = sum(claim.verification_status == VerificationStatus.UNKNOWN for claim in claims)
        return {
            "claim_count": total,
            "cited_claim_count": cited,
            "supported_claim_count": supported,
            "partially_supported_claim_count": partial,
            "contradicted_claim_count": contradicted,
            "unknown_claim_count": unknown,
            "citation_coverage": cited / total if total else 0.0,
            "citation_entailment": (supported + 0.5 * partial) / cited if cited else 0.0,
            "unsupported_claim_rate": (unknown + contradicted) / total if total else 0.0,
        }
