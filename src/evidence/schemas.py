"""Structured source, claim, and research-round schemas."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class SourceType(str, Enum):
    PAPER = "paper"
    OFFICIAL_DOC = "official_doc"
    OFFICIAL_REPOSITORY = "official_repository"
    REPOSITORY = "repository"
    INSTITUTIONAL = "institutional"
    TECH_MEDIA = "tech_media"
    BLOG = "blog"
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    SUPPORTED = "supported"
    PARTIALLY_SUPPORTED = "partially_supported"
    CONTRADICTED = "contradicted"
    UNKNOWN = "unknown"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Source:
    source_id: str
    url: str
    title: str = ""
    quote: str = ""
    publisher: str = ""
    source_type: SourceType = SourceType.UNKNOWN
    published_at: str = ""
    retrieved_at: str = field(default_factory=_utc_now)
    content_hash: str = ""
    quality_score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.content_hash:
            payload = f"{self.url}\n{self.title}\n{self.quote}".encode("utf-8")
            self.content_hash = hashlib.sha256(payload).hexdigest()
        self.quality_score = max(0.0, min(1.0, float(self.quality_score)))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["source_type"] = self.source_type.value
        data["snippet"] = self.quote
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Source":
        payload = dict(data)
        payload.pop("snippet", None)
        allowed = {
            "source_id", "url", "title", "quote", "publisher", "source_type",
            "published_at", "retrieved_at", "content_hash", "quality_score", "metadata",
        }
        extras = {key: value for key, value in payload.items() if key not in allowed}
        payload = {key: value for key, value in payload.items() if key in allowed}
        payload.setdefault("metadata", {}).update(extras)
        try:
            payload["source_type"] = SourceType(payload.get("source_type", "unknown"))
        except ValueError:
            payload["source_type"] = SourceType.UNKNOWN
        return cls(**payload)


@dataclass
class EvidenceSpan:
    source_id: str
    quote: str
    locator: str = ""
    overlap_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Claim:
    claim_id: str
    statement: str
    citations: list[str] = field(default_factory=list)
    evidence: list[EvidenceSpan] = field(default_factory=list)
    verification_status: VerificationStatus = VerificationStatus.UNKNOWN
    confidence: float = 0.0
    importance: str = "normal"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["verification_status"] = self.verification_status.value
        data["evidence"] = [item.to_dict() for item in self.evidence]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Claim":
        payload = dict(data)
        try:
            payload["verification_status"] = VerificationStatus(
                payload.get("verification_status", "unknown")
            )
        except ValueError:
            payload["verification_status"] = VerificationStatus.UNKNOWN
        payload["evidence"] = [
            item if isinstance(item, EvidenceSpan) else EvidenceSpan(**item)
            for item in payload.get("evidence", [])
        ]
        return cls(**payload)


@dataclass
class ResearchRound:
    round_id: int
    task_ids: list[str]
    source_count: int = 0
    claim_count: int = 0
    supported_claim_count: int = 0
    unresolved_questions: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    stop_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
