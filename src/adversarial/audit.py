"""Evidence-aware Red-Blue report audit.

The auditor is deliberately deterministic.  It does not replace the external
judge; it turns already extracted Claim/Evidence state into auditable repair
events that can be measured in an ablation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AuditIssue:
    claim_id: str
    action: str
    reason: str
    dimension: str = "citation"
    severity: str = "normal"
    resolved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "action": self.action,
            "reason": self.reason,
            "dimension": self.dimension,
            "severity": self.severity,
            "resolved": self.resolved,
        }


@dataclass
class AuditResult:
    content: str
    claims: list[dict[str, Any]]
    issues: list[AuditIssue] = field(default_factory=list)
    rounds: int = 0
    oscillation_count: int = 0
    deleted_claim_ids: list[str] = field(default_factory=list)
    _extra_metrics: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def issue_counts_by_dimension(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            counts[issue.dimension] = counts.get(issue.dimension, 0) + 1
        return counts

    @property
    def score(self) -> float:
        if not self.claims:
            # An empty claim set is only neutral for an empty report.  A
            # non-empty report with no atomic claims failed the audit surface.
            return 0.0 if self.content.strip() else 1.0
        unresolved = sum(
            1
            for claim in self.claims
            if claim.get("verification_status") in {"unknown", "contradicted"}
        )
        return max(0.0, 1.0 - unresolved / len(self.claims))

    def metrics(self) -> dict[str, Any]:
        return {
            "red_issue_count": len(self.issues),
            "blue_fix_acceptance_rate": (
                sum(issue.resolved for issue in self.issues) / len(self.issues)
                if self.issues
                else 1.0
            ),
            "adversarial_rounds": self.rounds,
            "oscillation_count": self.oscillation_count,
            "audit_score": round(self.score, 4),
            "deleted_claim_count": len(self.deleted_claim_ids),
            "red_issue_counts_by_dimension": self.issue_counts_by_dimension,
            **self._extra_metrics,
        }


class RedBlueAuditor:
    """Run bounded Red detection and conservative Blue repair."""

    def __init__(self, max_rounds: int = 2, expose_audit: bool = True) -> None:
        self.max_rounds = max(1, int(max_rounds))
        self.expose_audit = bool(expose_audit)

    def audit(
        self,
        content: str,
        claims: list[dict[str, Any]],
        enabled: bool = True,
    ) -> AuditResult:
        if not enabled:
            return AuditResult(content=content, claims=claims, rounds=0)

        working_claims = [dict(claim) for claim in claims]
        issues: list[AuditIssue] = []
        seen_states: set[tuple[tuple[str, str], ...]] = set()
        oscillation_count = 0
        current_content = content

        deleted_claim_ids: list[str] = []
        for round_index in range(1, self.max_rounds + 1):
            state = tuple(
                sorted(
                    (str(claim.get("claim_id", "")), str(claim.get("verification_status", "unknown")))
                    for claim in working_claims
                )
            )
            if state in seen_states:
                oscillation_count += 1
                break
            seen_states.add(state)

            round_issues: list[AuditIssue] = []
            if not working_claims and current_content.strip():
                round_issues.append(
                    AuditIssue(
                        claim_id="__report__",
                        action="ADD",
                        reason="no atomic claims were extracted from a non-empty report",
                        dimension="coverage",
                        severity="high",
                    )
                )
            for claim in working_claims:
                status = str(claim.get("verification_status", "unknown"))
                claim_id = str(claim.get("claim_id", ""))
                citations = claim.get("citations") or []
                if status == "contradicted":
                    round_issues.append(
                        AuditIssue(
                            claim_id,
                            "MODIFY",
                            "claim conflicts with linked evidence",
                            "numeric" if any(char.isdigit() for char in str(claim.get("statement", ""))) else "factual",
                            "high",
                        )
                    )
                elif status == "unknown" and citations:
                    round_issues.append(
                        AuditIssue(
                            claim_id,
                            "VERIFY",
                            "citation does not sufficiently support claim",
                            "citation",
                            "high",
                        )
                    )
                elif not citations and claim.get("metadata", {}).get("is_verifiable", True):
                    # Missing evidence is an audit finding, not proof that the
                    # claim is false.  Keep the claim visible and mark it for
                    # external verification; deleting it would artificially
                    # improve citation metrics by changing the denominator.
                    round_issues.append(
                        AuditIssue(
                            claim_id,
                            "VERIFY",
                            "verifiable claim has no citation",
                            "citation",
                            "high" if claim.get("importance") == "high" else "normal",
                        )
                    )

            if not round_issues:
                return AuditResult(
                    content=current_content,
                    claims=working_claims,
                    issues=issues,
                    rounds=round_index,
                    oscillation_count=oscillation_count,
                    deleted_claim_ids=deleted_claim_ids,
                )

            for issue in round_issues:
                claim = next(
                    (item for item in working_claims if str(item.get("claim_id", "")) == issue.claim_id),
                    None,
                )
                if claim is None:
                    if issue.action == "ADD" and issue.claim_id == "__report__":
                        issue.resolved = True
                        issues.append(issue)
                    continue
                # Blue is conservative: it never invents evidence. It lowers
                # unsupported claims to an explicit uncertainty marker.
                if issue.action == "DELETE":
                    statement = str(claim.get("statement", "")).strip()
                    if len(statement) >= 20 and statement in current_content:
                        current_content = current_content.replace(
                            statement,
                            "[证据不足，已省略该结论]",
                            1,
                        )
                        deleted_claim_ids.append(issue.claim_id)
                        issue.resolved = True
                elif issue.action in {"MODIFY", "VERIFY", "ADD"}:
                    claim.setdefault("metadata", {})["audit_action"] = issue.action
                    claim["metadata"]["audit_reason"] = issue.reason
                    if issue.action in {"MODIFY", "VERIFY"}:
                        claim["verification_status"] = "unknown"
                    issue.resolved = issue.action == "MODIFY"
                if issue.action == "ADD":
                    issue.resolved = True
                issues.append(issue)

            if deleted_claim_ids:
                working_claims = [
                    claim for claim in working_claims
                    if str(claim.get("claim_id", "")) not in set(deleted_claim_ids)
                ]

            # Make the repair visible to the user without deleting source text.
            unresolved = [
                issue.claim_id
                for issue in round_issues
                if issue.action in {"MODIFY", "VERIFY"}
            ]
            if self.expose_audit and unresolved and "## Evidence Audit" not in current_content:
                current_content = (
                    current_content.rstrip()
                    + "\n\n## Evidence Audit\n\n"
                    + "The following claims require additional verification: "
                    + ", ".join(unresolved)
                    + ".\n"
                )
            elif self.expose_audit and any(issue.action == "ADD" for issue in round_issues) and "## Evidence Audit" not in current_content:
                current_content = (
                    current_content.rstrip()
                    + "\n\n## Evidence Audit\n\n"
                    + "No atomic claims were extracted; the report requires a claim extraction pass.\n"
                )

        return AuditResult(
            content=current_content,
            claims=working_claims,
            issues=issues,
            rounds=self.max_rounds,
            oscillation_count=oscillation_count,
            deleted_claim_ids=deleted_claim_ids,
        )
