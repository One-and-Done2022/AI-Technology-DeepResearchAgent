"""External DeepSeek judge for report quality and claim-evidence support."""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from src.adversarial.json_fallback import parse_json_with_fallback
from src.utils.env_config import get_env
from src.utils.env_config import get_env_float


_VALID_STATUSES = {"supported", "partially_supported", "contradicted", "unknown"}


def parse_json_object(text: str) -> dict[str, Any]:
    value, _strategy = parse_json_with_fallback(text)
    return value


@dataclass
class JudgeResponse:
    value: dict[str, Any]
    usage: dict[str, int]
    elapsed_seconds: float


class DeepSeekJudge:
    def __init__(self, max_retries: int = 2) -> None:
        api_key = get_env("DEEPSEEK_API_KEY")
        base_url = get_env("DEEPSEEK_BASE_URL")
        model = get_env("DEEPSEEK_MODEL")
        if not api_key or not base_url or not model:
            raise ValueError("DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL and DEEPSEEK_MODEL are required")
        self.model: str = model
        self.client = OpenAI(
            api_key=api_key, base_url=base_url,
            timeout=get_env_float("DEEPSEEK_REQUEST_TIMEOUT", 60.0),
        )
        self.max_retries = max_retries

    def _request(self, system: str, user: str) -> JudgeResponse:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            try:
                strict_system = system
                if attempt > 0:
                    strict_system += " Return exactly one valid JSON object and no markdown, prose, or code fences."
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": strict_system}, {"role": "user", "content": user}],
                    temperature=0,
                    max_tokens=1200,
                )
                content = response.choices[0].message.content or ""
                raw_usage = response.usage
                usage = {
                    "input_tokens": int(getattr(raw_usage, "prompt_tokens", 0) or 0),
                    "output_tokens": int(getattr(raw_usage, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(raw_usage, "total_tokens", 0) or 0),
                }
                return JudgeResponse(parse_json_object(content), usage, time.monotonic() - started)
            except Exception as exc:
                last_error = exc
                status = getattr(exc, "status_code", None)
                retryable = (
                    isinstance(exc, ValueError)
                    or status in {429, 500, 502, 503, 504}
                    or "timeout" in str(exc).lower()
                )
                if attempt >= self.max_retries or not retryable:
                    break
                time.sleep(2 ** attempt)
        raise RuntimeError(f"Judge request failed: {type(last_error).__name__}: {last_error}")

    async def evaluate_report(
        self,
        query: str,
        content: str,
        context: dict[str, Any] | None = None,
    ) -> JudgeResponse:
        """Score report content with the benchmark context visible.

        ``context`` is deliberately data-only and must not contain the system
        name.  This lets the judge assess required topics and answerability,
        while keeping the content score separate from claim-level evidence
        judgments.
        """
        system = (
            "You are an independent evaluator of Chinese AI technology research reports. "
            "Return exactly one JSON object. Score content dimensions from 0 to 10. "
            "Use the benchmark context to check required coverage and answerability. "
            "Do not reward report length, citation formatting, or the presence of URLs by itself. "
            "Do not infer the producing system or compare against another report."
        )
        benchmark = context or {}
        user = json.dumps(
            {
                "query": query,
                "benchmark_context": {
                    "as_of": benchmark.get("as_of"),
                    "answerable": benchmark.get("answerable", True),
                    "expected_topics": benchmark.get("expected_topics", []),
                    "required_claims": benchmark.get("required_claims", []),
                    "sources": [
                        {
                            "source_id": source.get("source_id"),
                            "title": source.get("title"),
                            "url": source.get("url"),
                            "quote": (source.get("quote") or source.get("snippet", ""))[:600],
                        }
                        for source in benchmark.get("sources", [])[:20]
                    ],
                    "claims": [
                        {
                            "claim_id": claim.get("claim_id"),
                            "claim_type": claim.get("claim_type"),
                            "statement": claim.get("statement"),
                            "citations": claim.get("citations", []),
                        }
                        for claim in benchmark.get("claims", [])[:40]
                    ],
                },
                "report": content,
                "required_output": {
                    "factual_accuracy": 0,
                    "comprehensiveness": 0,
                    "analysis_quality": 0,
                    "presentation": 0,
                    "instruction_following": 0,
                    "reason": "brief Chinese explanation grounded in the benchmark context",
                    "content_limitations": [],
                },
            },
            ensure_ascii=False,
        )
        response = await asyncio.to_thread(self._request, system, user)
        for key in (
            "factual_accuracy", "comprehensiveness", "analysis_quality",
            "presentation", "instruction_following",
        ):
            response.value[key] = max(0.0, min(10.0, float(response.value.get(key, 0))))
        response.value["content_score"] = round(
            sum(response.value[key] for key in (
                "factual_accuracy", "comprehensiveness", "analysis_quality",
                "presentation", "instruction_following",
            )) / 5,
            4,
        )
        response.value["judge_context_used"] = {
            "as_of": benchmark.get("as_of"),
            "answerable": benchmark.get("answerable", True),
            "expected_topics_count": len(benchmark.get("expected_topics", [])),
            "required_claims_count": len(benchmark.get("required_claims", [])),
        }
        return response

    async def evaluate_claim(
        self, query: str, claim: dict[str, Any], sources: list[dict[str, Any]]
    ) -> JudgeResponse:
        source_map = {source.get("source_id"): source for source in sources}
        cited = [source_map[item] for item in claim.get("citations", []) if item in source_map]
        system = (
            "Determine whether the cited evidence supports one atomic claim. Return JSON only. "
            "Allowed status: supported, partially_supported, contradicted, unknown."
        )
        user = json.dumps(
            {
                "query": query,
                "claim": claim.get("statement", ""),
                "claim_type": claim.get("claim_type", "definition"),
                "evidence": [
                    {"source_id": s.get("source_id"), "title": s.get("title"),
                     "url": s.get("url"), "quote": s.get("quote") or s.get("snippet", "")}
                    for s in cited
                ],
                "required_output": {"status": "unknown", "confidence": 0.0, "reason": ""},
            },
            ensure_ascii=False,
        )
        response = await asyncio.to_thread(self._request, system, user)
        status = str(response.value.get("status", "unknown")).lower()
        response.value["status"] = status if status in _VALID_STATUSES else "unknown"
        response.value["confidence"] = max(0.0, min(1.0, float(response.value.get("confidence", 0))))
        return response


def summarize_claim_judgments(claims: list[dict[str, Any]], judgments: list[dict[str, Any]]) -> dict[str, float]:
    verifiable = [
        claim for claim in claims
        if claim.get("metadata", {}).get(
            "is_verifiable", claim.get("claim_type") != "recommendation"
        )
    ]
    claim_ids = {claim.get("claim_id") for claim in verifiable}
    relevant = [item for item in judgments if item.get("claim_id") in claim_ids]
    total = len(verifiable)
    cited = sum(bool(claim.get("citations")) for claim in verifiable)
    counts = {status: 0 for status in _VALID_STATUSES}
    for judgment in relevant:
        counts[judgment.get("status", "unknown")] += 1
    important_ids = {
        claim.get("claim_id") for claim in verifiable if claim.get("importance") == "high"
    }
    unsupported_important = sum(
        item.get("status", "unknown") in {"unknown", "contradicted"}
        for item in relevant if item.get("claim_id") in important_ids
    )
    return {
        "citation_coverage": cited / total if total else 0.0,
        "citation_correctness": (counts["supported"] + 0.5 * counts["partially_supported"]) / cited if cited else 0.0,
        "unsupported_claim_rate": (counts["unknown"] + counts["contradicted"] + max(0, total - len(relevant))) / total if total else 1.0,
        "contradicted_claim_rate": counts["contradicted"] / total if total else 0.0,
        "citation_completeness": cited / total if total else 0.0,
        "unsupported_important_claim_rate": (
            unsupported_important / len(important_ids) if important_ids else 0.0
        ),
    }
