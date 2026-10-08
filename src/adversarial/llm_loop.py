"""Optional LLM-backed Red/Blue adversarial audit.

The deterministic :mod:`src.adversarial.audit` path remains the default for
reproducible benchmark runs.  This module provides the richer Red/Blue
interaction described in the project design without changing the
Claim--Evidence schema or allowing the auditor to invent evidence.
"""
from __future__ import annotations

import json
from collections import Counter
from typing import Any

from .audit import AuditIssue, AuditResult, RedBlueAuditor
from .json_fallback import parse_json_with_fallback


_RED_SYSTEM = (
    "You are the Red Agent for an evidence-driven technical research report. "
    "Audit only against the supplied claims and sources. Never invent evidence. "
    "Return one JSON object and no markdown."
)

_RED_USER = """Audit this report and return JSON with this exact shape:
{
  "dimensions": {
    "factual_accuracy": 0,
    "logical_consistency": 0,
    "citation_quality": 0,
    "numeric_consistency": 0,
    "coverage": 0
  },
  "issues": [
    {
      "claim_id": "C1",
      "dimension": "factual|logical|citation|numeric|coverage",
      "action": "ADD|DELETE|MODIFY|VERIFY",
      "severity": "high|normal|low",
      "reason": "short evidence-grounded explanation"
    }
  ]
}

Question:
{query}

Report:
{content}

Claims:
{claims}

Sources:
{sources}
"""

_BLUE_SYSTEM = (
    "You are the Blue Agent. Repair a technical report conservatively using only "
    "the supplied report, claims, issues and sources. Never invent a citation or "
    "new factual detail. Return one JSON object and no markdown."
)

_BLUE_USER = """Return JSON with this exact shape:
{
  "content": "the complete revised report",
  "operations": [
    {"claim_id": "C1", "action": "ADD|DELETE|MODIFY|VERIFY", "resolved": true}
  ]
}

Question:
{query}

Original report:
{content}

Red issues:
{issues}

Claims:
{claims}

Sources:
{sources}
"""

_VALID_ACTIONS = {"ADD", "DELETE", "MODIFY", "VERIFY"}
_VALID_DIMENSIONS = {"factual", "logical", "citation", "numeric", "coverage"}


def _content(response: Any) -> str:
    if isinstance(response, dict):
        return str(response.get("content", "") or "")
    return str(getattr(response, "content", "") or "")


def _bounded_json(value: Any, limit: int = 12000) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)[:limit]


class LLMRedBlueAuditor:
    """Bounded Red/Blue loop with deterministic fallback and parse telemetry."""

    requires_context = True

    def __init__(
        self,
        policy: Any,
        max_rounds: int = 2,
        max_tokens: int = 2048,
        fallback: RedBlueAuditor | None = None,
    ) -> None:
        self.policy = policy
        self.max_rounds = max(1, int(max_rounds))
        self.max_tokens = max(256, int(max_tokens))
        self.fallback = fallback or RedBlueAuditor(max_rounds=self.max_rounds)

    def _call(self, messages: list[dict[str, str]]) -> str:
        old_max = getattr(self.policy, "max_tokens", None)
        try:
            if old_max is not None:
                self.policy.max_tokens = self.max_tokens
            return _content(self.policy(messages))
        finally:
            if old_max is not None:
                self.policy.max_tokens = old_max

    @staticmethod
    def _sources_text(sources: list[dict[str, Any]]) -> str:
        if not sources:
            return "[]"
        return _bounded_json([
            {
                "source_id": source.get("source_id", ""),
                "title": source.get("title", ""),
                "url": source.get("url", ""),
                "quote": source.get("quote") or source.get("snippet", ""),
            }
            for source in sources[:15]
        ])

    def _parse(self, raw: str, telemetry: Counter[str]) -> dict[str, Any] | None:
        try:
            value, strategy = parse_json_with_fallback(raw)
        except ValueError:
            telemetry["parse_failures"] += 1
            return None
        telemetry["parse_successes"] += 1
        telemetry[f"parse_strategy:{strategy}"] += 1
        return value

    def _red_attack(
        self,
        query: str,
        content: str,
        claims: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        telemetry: Counter[str],
    ) -> dict[str, Any] | None:
        prompt = _RED_USER
        for key, value in {
            "query": query[:2000],
            "content": content[:12000],
            "claims": _bounded_json(claims),
            "sources": self._sources_text(sources),
        }.items():
            prompt = prompt.replace("{" + key + "}", value)
        raw = self._call([
            {"role": "system", "content": _RED_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        return self._parse(raw, telemetry)

    def _blue_repair(
        self,
        query: str,
        content: str,
        claims: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        issues: list[dict[str, Any]],
        telemetry: Counter[str],
    ) -> dict[str, Any] | None:
        prompt = _BLUE_USER
        for key, value in {
            "query": query[:2000],
            "content": content[:12000],
            "claims": _bounded_json(claims),
            "issues": _bounded_json(issues),
            "sources": self._sources_text(sources),
        }.items():
            prompt = prompt.replace("{" + key + "}", value)
        raw = self._call([
            {"role": "system", "content": _BLUE_SYSTEM},
            {"role": "user", "content": prompt},
        ])
        return self._parse(raw, telemetry)

    @staticmethod
    def _normalise_issues(raw: Any) -> list[AuditIssue]:
        if not isinstance(raw, list):
            return []
        issues: list[AuditIssue] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action", "VERIFY")).upper()
            dimension = str(item.get("dimension", "citation")).lower()
            if action not in _VALID_ACTIONS:
                action = "VERIFY"
            if dimension not in _VALID_DIMENSIONS:
                dimension = "citation"
            issues.append(AuditIssue(
                claim_id=str(item.get("claim_id", "__report__")),
                action=action,
                reason=str(item.get("reason", ""))[:500],
                dimension=dimension,
                severity=str(item.get("severity", "normal")),
            ))
        return issues

    def audit(
        self,
        content: str,
        claims: list[dict[str, Any]],
        enabled: bool = True,
        query: str = "",
        sources: list[dict[str, Any]] | None = None,
    ) -> AuditResult:
        if not enabled:
            return AuditResult(content=content, claims=claims, rounds=0)
        if self.policy is None:
            return self.fallback.audit(content, claims, enabled=True)

        sources = sources or []
        current_content = content
        current_claims = [dict(claim) for claim in claims]
        all_issues: list[AuditIssue] = []
        telemetry: Counter[str] = Counter()
        seen_states: set[tuple[tuple[str, str], ...]] = set()
        oscillation_count = 0

        for round_index in range(1, self.max_rounds + 1):
            state = tuple(sorted(
                (str(claim.get("claim_id", "")), str(claim.get("verification_status", "unknown")))
                for claim in current_claims
            ))
            if state in seen_states:
                oscillation_count += 1
                break
            seen_states.add(state)

            verdict = self._red_attack(query, current_content, current_claims, sources, telemetry)
            if verdict is None:
                fallback_result = self.fallback.audit(current_content, current_claims, enabled=True)
                fallback_result.rounds = round_index
                fallback_result.oscillation_count = oscillation_count
                fallback_result.issues.extend(all_issues)
                fallback_result._extra_metrics = {"llm_audit_fallback": True, **telemetry}
                return fallback_result

            issues = self._normalise_issues(verdict.get("issues"))
            all_issues.extend(issues)
            if not issues:
                break

            repaired = self._blue_repair(
                query, current_content, current_claims, sources,
                [issue.to_dict() for issue in issues], telemetry,
            )
            if repaired is None:
                break
            revised = repaired.get("content")
            if isinstance(revised, str) and revised.strip() and len(revised) <= max(20000, len(current_content) * 3):
                current_content = revised
            resolved = {
                str(item.get("claim_id")): bool(item.get("resolved", False))
                for item in repaired.get("operations", [])
                if isinstance(item, dict)
            }
            for issue in issues:
                issue.resolved = resolved.get(issue.claim_id, False)
                claim = next((item for item in current_claims if str(item.get("claim_id")) == issue.claim_id), None)
                if claim is not None:
                    claim.setdefault("metadata", {})["audit_action"] = issue.action
                    claim["metadata"]["audit_dimension"] = issue.dimension
                    claim["metadata"]["audit_reason"] = issue.reason
                    if issue.action in {"MODIFY", "VERIFY"} and issue.resolved:
                        claim["verification_status"] = "unknown"

        attempts = telemetry["parse_successes"] + telemetry["parse_failures"]
        extra = {
            "llm_audit_fallback": False,
            "json_parse_success_rate": telemetry["parse_successes"] / attempts if attempts else 0.0,
            "json_parse_attempts": attempts,
            "json_parse_successes": telemetry["parse_successes"],
            "json_parse_failures": telemetry["parse_failures"],
            "json_parse_strategies": {
                key.split(":", 1)[1]: value
                for key, value in telemetry.items()
                if key.startswith("parse_strategy:")
            },
        }
        result = AuditResult(
            content=current_content,
            claims=current_claims,
            issues=all_issues,
            rounds=min(self.max_rounds, len(seen_states)),
            oscillation_count=oscillation_count,
        )
        result._extra_metrics = extra
        return result
