"""Deterministic source classification and quality scoring."""
from __future__ import annotations

from urllib.parse import urlparse

from .schemas import SourceType


_PAPER_DOMAINS = {
    "arxiv.org",
    "openreview.net",
    "aclanthology.org",
    "dl.acm.org",
    "ieeexplore.ieee.org",
    "proceedings.neurips.cc",
}
_OFFICIAL_DOC_HINTS = (
    "docs.",
    "documentation.",
    "developer.",
    "developers.",
    "kubernetes.io",
    "pytorch.org",
    "tensorflow.org",
    "huggingface.co/docs",
)
_INSTITUTIONAL_SUFFIXES = (".edu", ".gov", ".ac.uk", ".edu.cn", ".gov.cn")
_TECH_MEDIA_DOMAINS = {
    "techcrunch.com",
    "theregister.com",
    "infoq.com",
    "arstechnica.com",
    "36kr.com",
}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def classify_source(url: str, title: str = "", metadata: dict | None = None) -> SourceType:
    metadata = metadata or {}
    explicit = str(metadata.get("source_type", "")).lower()
    if explicit in {item.value for item in SourceType}:
        return SourceType(explicit)

    host = _host(url)
    path = urlparse(url).path.lower() if url else ""
    title_lower = title.lower()

    if host in _PAPER_DOMAINS or "paper" in metadata.get("kind", ""):
        return SourceType.PAPER
    if host == "github.com":
        return SourceType.REPOSITORY
    if any(hint in f"{host}{path}" for hint in _OFFICIAL_DOC_HINTS):
        return SourceType.OFFICIAL_DOC
    if host.endswith(_INSTITUTIONAL_SUFFIXES):
        return SourceType.INSTITUTIONAL
    if host in _TECH_MEDIA_DOMAINS:
        return SourceType.TECH_MEDIA
    if any(word in title_lower for word in ("blog", "博客", "medium")):
        return SourceType.BLOG
    return SourceType.UNKNOWN


def score_source(source_type: SourceType, url: str = "", quote: str = "") -> float:
    base = {
        SourceType.PAPER: 1.0,
        SourceType.OFFICIAL_DOC: 0.95,
        SourceType.OFFICIAL_REPOSITORY: 0.90,
        SourceType.REPOSITORY: 0.75,
        SourceType.INSTITUTIONAL: 0.85,
        SourceType.TECH_MEDIA: 0.65,
        SourceType.BLOG: 0.45,
        SourceType.UNKNOWN: 0.35,
    }[source_type]
    if not url:
        base -= 0.20
    if len(quote.strip()) < 40:
        base -= 0.10
    return round(max(0.0, min(1.0, base)), 3)
