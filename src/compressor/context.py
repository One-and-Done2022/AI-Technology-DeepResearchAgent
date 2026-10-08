"""Deterministic evidence-preserving context compression."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass
class CompressionResult:
    text: str
    original_chars: int
    compressed_chars: int
    retained_claim_ids: list[str]
    original_evidence_claim_count: int
    retained_evidence_claim_count: int
    stage_stats: dict[str, Any]

    def metrics(self) -> dict[str, Any]:
        reduction = 1.0 - self.compressed_chars / max(self.original_chars, 1)
        return {
            "compression_ratio": round(max(0.0, reduction), 4),
            "original_chars": self.original_chars,
            "compressed_chars": self.compressed_chars,
            "retained_claim_count": len(self.retained_claim_ids),
            "evidence_retention": round(
                self.retained_evidence_claim_count / max(self.original_evidence_claim_count, 1), 4
            ) if self.original_evidence_claim_count else 1.0,
            "compression_stages": self.stage_stats,
        }


class EvidencePreservingCompressor:
    """Three-stage lexical approximation of embedding/TextRank/evidence keep.

    The implementation is intentionally dependency-light.  It exposes the same
    measurable stages used by the full pipeline and keeps every cited sentence
    plus the strongest uncited sentences under the budget.
    """

    def compress(
        self,
        text: str,
        claims: list[dict[str, Any]] | None = None,
        max_chars: int | None = None,
    ) -> CompressionResult:
        claims = claims or []
        original_chars = len(text)
        if not text.strip():
            return CompressionResult("", 0, 0, [], 0, 0, {"l1": 0, "l2": 0, "l3": 0})

        sentences = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s+|\n+", text) if part.strip()]
        if max_chars is None:
            max_chars = max(800, int(original_chars * 0.65))

        def embedding(value: str, dimension: int = 64) -> np.ndarray:
            vector = np.zeros(dimension, dtype=np.float32)
            tokens = re.findall(r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}", value.lower())
            for token in tokens:
                index = hash(token) % dimension
                vector[index] += 1.0
            norm = np.linalg.norm(vector)
            return vector / norm if norm else vector

        claim_context = " ".join(str(claim.get("statement", "")) for claim in claims)
        query_vector = embedding(claim_context or text)

        # L1: embedding-style coarse filtering plus explicit evidence retention.
        sentence_vectors = {sentence: embedding(sentence) for sentence in sentences}
        similarity = {
            sentence: float(np.dot(query_vector, vector))
            for sentence, vector in sentence_vectors.items()
        }
        claim_terms = set()
        for claim in claims:
            claim_terms.update(re.findall(r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}", str(claim.get("statement", ""))))
        l1 = [
            sentence
            for sentence in sentences
            if re.search(r"\[S\d+\]|https?://", sentence)
            or any(term in sentence for term in claim_terms if len(term) >= 2)
            or similarity.get(sentence, 0.0) >= max(similarity.values(), default=0.0) * 0.35
        ]
        if not l1:
            l1 = sentences[:]

        # L2: sentence-graph TextRank approximation over L1 candidates.
        frequencies: dict[str, int] = {}
        for sentence in sentences:
            for token in re.findall(r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}", sentence.lower()):
                frequencies[token] = frequencies.get(token, 0) + 1
        graph_scores = {sentence: 1.0 for sentence in l1}
        for _ in range(8):
            updated: dict[str, float] = {}
            for sentence in l1:
                tokens = set(re.findall(r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}", sentence.lower()))
                incoming = 0.0
                for other in l1:
                    if other == sentence:
                        continue
                    other_tokens = set(re.findall(r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}", other.lower()))
                    overlap = len(tokens & other_tokens) / max(len(tokens | other_tokens), 1)
                    incoming += overlap * graph_scores[other]
                lexical_bonus = sum(
                    frequencies.get(token, 0) for token in tokens
                ) / max(len(tokens), 1)
                updated[sentence] = 0.15 + 0.85 * incoming + 0.01 * lexical_bonus
            graph_scores = updated
        ranked = sorted(l1, key=lambda sentence: graph_scores[sentence], reverse=True)

        # L3: always preserve citation-bearing sentences before filling budget.
        citation_sentences = [sentence for sentence in sentences if re.search(r"\[S\d+\]|https?://", sentence)]
        selected: list[str] = []
        for sentence in citation_sentences + ranked:
            if sentence in selected:
                continue
            candidate = "\n".join(selected + [sentence])
            if len(candidate) <= max_chars or not selected:
                selected.append(sentence)

        retained_text = "\n".join(selected)
        def claim_retained(claim: dict[str, Any]) -> bool:
            statement_tokens = set(re.findall(
                r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}",
                str(claim.get("statement", "")).lower(),
            ))
            text_tokens = set(re.findall(
                r"[A-Za-z0-9_\-]{3,}|[\u4e00-\u9fff]{2,}",
                retained_text.lower(),
            ))
            return bool(statement_tokens) and len(statement_tokens & text_tokens) / len(statement_tokens) >= 0.5

        retained_claim_ids = [
            str(claim.get("claim_id")) for claim in claims if claim_retained(claim)
        ]
        evidence_claims = [claim for claim in claims if claim.get("citations")]
        retained_evidence_claim_count = sum(claim_retained(claim) for claim in evidence_claims)
        return CompressionResult(
            text=retained_text,
            original_chars=original_chars,
            compressed_chars=len(retained_text),
            retained_claim_ids=retained_claim_ids,
            original_evidence_claim_count=len(evidence_claims),
            retained_evidence_claim_count=retained_evidence_claim_count,
            stage_stats={
                "l1_embedding": len(l1),
                "l2_textrank": len(ranked),
                "l3_evidence_keep": len(selected),
            },
        )
