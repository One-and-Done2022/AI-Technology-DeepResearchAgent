"""Normalize tool observations and extract cited claims from reports."""
from __future__ import annotations

import re
from typing import Any, Iterable

from .schemas import Claim, ClaimType, Source
from .source_quality import classify_source, score_source
from .verifier import EvidenceVerifier, evidence_overlap


_CITATION_RE = re.compile(r"\[(S\d+)\]", re.IGNORECASE)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?])\s*|\n+")
_CLAUSE_SPLIT_RE = re.compile(r"[；;]|，(?:并且?|且|同时|而且)")
_ENTITY_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z][A-Za-z0-9+.-]{2,}|[A-Za-z]+-[A-Za-z0-9-]+)(?![A-Za-z0-9])"
)


def classify_claim(statement: str) -> ClaimType:
    lowered = statement.lower()
    rules = (
        (ClaimType.NEGATIVE, ("不存在", "无法验证", "证据不足", "cannot verify", "does not exist")),
        (ClaimType.LICENSE, ("license", "许可证", "许可协议")),
        (ClaimType.COST, ("成本", "价格", "费用", "显存", "cost", "price")),
        (ClaimType.TEMPORAL, ("发布", "版本", "更新", "日期", "release", "version")),
        (ClaimType.ADOPTION, ("star", "用户", "采用", "部署规模", "adoption")),
        (ClaimType.RECOMMENDATION, ("建议", "适合", "推荐", "选型", "should")),
        (ClaimType.PERFORMANCE, ("性能", "吞吐", "延迟", "准确率", "提升", "降低", "%", "throughput", "latency")),
        (ClaimType.COMPARISON, ("相比", "高于", "低于", "优于", "区别", "versus", " vs ", "compare")),
        (ClaimType.MECHANISM, ("通过", "使用", "采用", "机制", "原理", "架构", "uses", "via")),
    )
    for claim_type, markers in rules:
        if any(marker in lowered for marker in markers):
            return claim_type
    return ClaimType.DEFINITION


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
    for sentence in _SENTENCE_SPLIT_RE.split(text):
        # Markdown structure and table scaffolding are not atomic claims.
        # Keeping them out prevents headings and separators from inflating
        # unsupported-claim denominators.
        normalized_line = sentence.strip()
        if (
            not normalized_line
            or re.match(r"^#{1,6}\s+", normalized_line)
            or (normalized_line.startswith("|") and normalized_line.endswith("|"))
            or re.fullmatch(r"\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?", normalized_line)
            or re.fullmatch(r"[-|:\s]+", normalized_line)
        ):
            continue
        sentence_citations = [item.upper() for item in _CITATION_RE.findall(sentence)]
        sentence_citations = [item for item in sentence_citations if item in source_ids]
        for raw in _CLAUSE_SPLIT_RE.split(sentence):
            statement = re.sub(r"^\s*(?:[-*]|\d+[.)、])\s*", "", raw).strip()
            statement = re.sub(r"^#{1,6}\s*", "", statement)
            if len(statement) < 8 or len(statement) > 700:
                continue
            if statement.lower().startswith(("http://", "https://")):
                continue
            clean_statement = _CITATION_RE.sub("", statement).strip()
            if not clean_statement:
                continue
            if clean_statement.endswith(":") or re.fullmatch(r"[-|:\s]+", clean_statement):
                continue
            claim_type = classify_claim(clean_statement)
            claims.append(
                Claim(
                    claim_id=f"C{len(claims) + 1}",
                    statement=clean_statement,
                    claim_type=claim_type,
                    citations=list(dict.fromkeys(sentence_citations)),
                    importance="high" if re.search(r"\d|%|性能|成本|版本|发布|提升|降低", clean_statement) else "normal",
                    metadata={"is_verifiable": claim_type != ClaimType.RECOMMENDATION},
                )
            )
    return claims


class EvidencePipeline:
    def __init__(self, verifier: EvidenceVerifier | None = None, verify: bool = True) -> None:
        self.verifier = verifier or EvidenceVerifier()
        self.verify = verify

    def sources_from_trajectory(self, trajectory: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        return [source.to_dict() for source in normalize_sources(trajectory)]

    def build_claims(self, text: str, sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
        source_models = [Source.from_dict(source) for source in sources]
        claims = extract_claims(text, source_models)
        # Citation binding is part of the shared post-processing contract for
        # every sourced system.  `verify=False` means the system does not run
        # internal entailment/status verification; it must not mean that
        # Source/Claim/Citation links disappear altogether.
        if source_models:
            for claim in claims:
                if claim.citations or not claim.metadata.get("is_verifiable", True):
                    continue
                ranked = sorted(
                    (
                        (
                            max(
                                evidence_overlap(claim.statement, source.quote),
                                evidence_overlap(claim.statement, source.title),
                            ),
                            source.source_id,
                            "quote" if evidence_overlap(claim.statement, source.quote) >= evidence_overlap(claim.statement, source.title) else "title",
                        )
                        for source in source_models
                        if (source.quote or source.title).strip()
                    ),
                    reverse=True,
                )
                title_threshold = max(0.25, min(0.35, self.verifier.support_threshold))
                if ranked and ranked[0][0] >= (
                    title_threshold if ranked[0][2] == "title" else max(0.35, self.verifier.support_threshold)
                ):
                    overlap, source_id, binding_field = ranked[0]
                    claim.citations = [source_id]
                    claim.metadata["citation_binding"] = "lexical_candidate"
                    claim.metadata["binding_field"] = binding_field
                    claim.metadata["binding_overlap"] = round(overlap, 3)
                    continue

                # Abstract wording can differ substantially from the report,
                # while a named technical entity remains stable (QLoRA,
                # FlashAttention, mixture-of-experts). Bind this only as a
                # reviewable candidate; the verifier still decides whether it
                # is actually supported and cannot inflate entailment.
                claim_entities = {
                    token.lower() for token in _ENTITY_TOKEN_RE.findall(claim.statement)
                }
                if claim_entities:
                    for source in source_models:
                        source_entities = {
                            token.lower()
                            for token in _ENTITY_TOKEN_RE.findall(
                                f"{source.title} {source.quote}"
                            )
                        }
                        common_entities = claim_entities & source_entities
                        if common_entities:
                            claim.citations = [source.source_id]
                            claim.metadata["citation_binding"] = "entity_anchor"
                            claim.metadata["entity_anchor"] = sorted(common_entities)
                            break
        verified = self.verifier.verify_all(claims, source_models) if self.verify else claims
        return [claim.to_dict() for claim in verified]

    @staticmethod
    def annotate_citations(text: str, claims: list[dict[str, Any]]) -> str:
        """Make already-bound citations visible without inventing new evidence.

        This only appends source IDs that are already present in a Claim.  It
        never binds a new source and never changes the verification status.
        """
        annotated = text
        for claim in claims:
            statement = str(claim.get("statement", "")).strip()
            citations = [str(item).upper() for item in claim.get("citations", []) if item]
            if len(statement) < 8 or not citations or statement not in annotated:
                continue
            start = annotated.find(statement)
            tail = annotated[start + len(statement): start + len(statement) + 20]
            if any(f"[{citation}]" in tail for citation in citations):
                continue
            annotated = annotated.replace(
                statement,
                statement + " " + " ".join(f"[{citation}]" for citation in citations),
                1,
            )
        return annotated

    def build(self, text: str, trajectory: Iterable[dict[str, Any]]) -> tuple[list[dict], list[dict], dict]:
        sources = self.sources_from_trajectory(trajectory)
        claims = self.build_claims(text, sources)
        summary = self.verifier.summarize([Claim.from_dict(claim) for claim in claims])
        return sources, claims, summary

    def refresh(self, text: str, sources: list[dict[str, Any]]) -> tuple[list[dict], dict]:
        claims = self.build_claims(text, sources)
        summary = self.verifier.summarize([Claim.from_dict(claim) for claim in claims])
        return claims, summary
