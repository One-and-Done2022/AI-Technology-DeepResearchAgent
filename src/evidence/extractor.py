"""Normalize tool observations and extract cited claims from reports."""
from __future__ import annotations

import re
from typing import Any, Iterable

from .schemas import Claim, Source
from .source_quality import classify_source, score_source
from .verifier import EvidenceVerifier


_CITATION_RE = re.compile(r"\[(S\d+)\]", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])\s*|\n+")


def _make_source(url: str, title: str, quote: str, metadata: dict[str, Any]) -> Source:
    source_type = classify_source(url, title, metadata)
    return Source(
        source_id="",
        url=url,
        title=title.strip(),
        quote=quote.strip(),
        publisher=str(metadata.get("publisher", "")),
        source_type=source_type,
        published_at=str(metadata.get("published_at", metadata.get("published", ""))),
        quality_score=score_source(source_type, url, quote),
        metadata=metadata,
    )


def normalize_sources(trajectory: Iterable[dict[str, Any]]) -> list[Source]:
    candidates: list[Source] = []
    for step in trajectory:
        if step.get("role") != "tool":
            continue
        name = str(step.get("name", ""))
        result = step.get("result")
        args = step.get("arguments") or {}

        if name == "web_search" and isinstance(result, dict):
            for item in result.get("results", []):
                if not isinstance(item, dict):
                    continue
                candidates.append(
                    _make_source(
                        str(item.get("url", "")),
                        str(item.get("title", "")),
                        str(item.get("snippet", "")),
                        {"tool": name, "backend": result.get("source", "")},
                    )
                )
        elif name == "arxiv_reader" and isinstance(result, dict):
            for paper in result.get("papers", []):
                if not isinstance(paper, dict):
                    continue
                candidates.append(
                    _make_source(
                        str(paper.get("pdf_url") or paper.get("url") or ""),
                        str(paper.get("title", "")),
                        str(paper.get("summary") or paper.get("abstract") or ""),
                        {
                            "tool": name,
                            "kind": "paper",
                            "published": paper.get("published") or paper.get("year") or "",
                            "authors": paper.get("authors", []),
                        },
                    )
                )
        elif name == "github_reader" and isinstance(result, dict) and not result.get("error"):
            candidates.append(
                _make_source(
                    str(result.get("html_url", "")),
                    str(result.get("full_name", "")),
                    str(result.get("readme") or result.get("description") or ""),
                    {
                        "tool": name,
                        "source_type": "official_repository",
                        "stars": result.get("stars", 0),
                        "updated_at": result.get("updated_at", ""),
                        "latest_release": result.get("latest_release", {}),
                    },
                )
            )
        elif name == "browser" and isinstance(result, str):
            url = str(args.get("url", ""))
            candidates.append(
                _make_source(url, url, result[:4000], {"tool": name})
            )

    unique: list[Source] = []
    seen: set[str] = set()
    for source in candidates:
        key = source.url or source.content_hash
        if not key or key in seen:
            continue
        seen.add(key)
        source.source_id = f"S{len(unique) + 1}"
        unique.append(source)
    return unique


def extract_claims(text: str, sources: list[Source]) -> list[Claim]:
    source_ids = {source.source_id for source in sources}
    claims: list[Claim] = []
    for raw in _SENTENCE_SPLIT_RE.split(text):
        statement = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", raw).strip()
        statement = re.sub(r"^#{1,6}\s*", "", statement)
        if len(statement) < 18 or len(statement) > 700:
            continue
        if statement.lower().startswith(("http://", "https://")):
            continue
        citations = [item.upper() for item in _CITATION_RE.findall(statement)]
        citations = [item for item in citations if item in source_ids]
        clean_statement = _CITATION_RE.sub("", statement).strip()
        if not clean_statement:
            continue
        claims.append(
            Claim(
                claim_id=f"C{len(claims) + 1}",
                statement=clean_statement,
                citations=list(dict.fromkeys(citations)),
                importance="high" if re.search(r"\d|%|性能|成本|版本|发布|提升|降低", clean_statement) else "normal",
            )
        )
    return claims


class EvidencePipeline:
    def __init__(self, verifier: EvidenceVerifier | None = None) -> None:
        self.verifier = verifier or EvidenceVerifier()

    def sources_from_trajectory(self, trajectory: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [source.to_dict() for source in normalize_sources(trajectory)]

    def build_claims(self, text: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        source_models = [Source.from_dict(source) for source in sources]
        claims = extract_claims(text, source_models)
        verified = self.verifier.verify_all(claims, source_models)
        return [claim.to_dict() for claim in verified]

    def build(self, text: str, trajectory: Iterable[dict[str, Any]]) -> tuple[list[dict], list[dict], dict]:
        sources = self.sources_from_trajectory(trajectory)
        claims = self.build_claims(text, sources)
        summary = self.verifier.summarize([Claim.from_dict(claim) for claim in claims])
        return sources, claims, summary

    def refresh(self, text: str, sources: list[dict[str, Any]]) -> tuple[list[dict], dict]:
        claims = self.build_claims(text, sources)
        summary = self.verifier.summarize([Claim.from_dict(claim) for claim in claims])
        return claims, summary
