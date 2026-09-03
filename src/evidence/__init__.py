"""Evidence-grounding primitives for technology research."""
from __future__ import annotations

from .extractor import EvidencePipeline, extract_claims, normalize_sources
from .schemas import Claim, EvidenceSpan, ResearchRound, Source, SourceType, VerificationStatus
from .source_quality import classify_source, score_source
from .store import EvidenceStore
from .verifier import EvidenceVerifier

__all__ = [
    "Claim",
    "EvidencePipeline",
    "EvidenceSpan",
    "EvidenceStore",
    "EvidenceVerifier",
    "ResearchRound",
    "Source",
    "SourceType",
    "VerificationStatus",
    "classify_source",
    "extract_claims",
    "normalize_sources",
    "score_source",
]
