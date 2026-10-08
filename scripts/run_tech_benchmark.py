#!/usr/bin/env python3
"""Run a resumable TechResearchBench comparison and aggregate results."""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.benchmarks.tech_research_bench import TechResearchBench
from evaluation.judge import DeepSeekJudge, summarize_claim_judgments
from evaluation.metrics.stats import bootstrap_ci_paired, paired_cohens_dz
from src.core.runner import initialize_modules, load_config, run_research_report, serialize_report
from src.evidence.extractor import EvidencePipeline
from src.models.model_router import ModelRouter
from src.models.vllm_policy import configure_global_request_limiter
from src.orchestrator.schemas import ResearchReport
from src.tools.web_search import WebSearchTool
from src.utils.env_config import get_env, get_env_float


SYSTEMS = (
    "direct_llm",
    "search_agent",
    "evidence_agent",
    "full_iterresearch",
    "full_stack",
    "full_stack_without_redblue",
    "full_stack_without_compressor",
    "full_stack_without_memory",
)
DEFAULT_SYSTEMS = (
    "direct_llm",
    "search_agent",
    "evidence_agent",
    "full_stack",
)
COMPARISONS = (
    ("direct_llm", "search_agent"), ("search_agent", "evidence_agent"),
    ("evidence_agent", "full_stack"), ("direct_llm", "full_stack"),
)


class AdaptiveLimiter:
    def __init__(self, limit: int) -> None:
        self.limit = max(1, limit)
        self.active = 0
        self.condition = asyncio.Condition()

    @asynccontextmanager
    async def slot(self):
        async with self.condition:
            await self.condition.wait_for(lambda: self.active < self.limit)
            self.active += 1
        try:
            yield
        finally:
            async with self.condition:
                self.active -= 1
                self.condition.notify_all()

    async def halve(self) -> None:
        async with self.condition:
            self.limit = max(1, self.limit // 2)
            self.condition.notify_all()


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _upsert_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    records = _load_records(path)
    by_key = {item.get("record_key"): item for item in records}
    by_key[record["record_key"]] = record
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for item in by_key.values():
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _stable_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:16]


def _git_commit() -> str:
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT_ROOT,
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _config_for_system(base: dict[str, Any], system: str) -> dict[str, Any]:
    cfg = copy.deepcopy(base)
    cfg.setdefault("model", {})["backend"] = "qwen"
    cfg["model"]["backend_mapping"] = {name: "qwen" for name in ("planner", "solver", "summarizer")}
    cfg["model"]["fresh_instances"] = True
    cfg["model"].setdefault("backend_sampling", {}).setdefault("qwen", {})["strict_errors"] = True
    cfg.setdefault("evidence", {})["enabled"] = False
    full_stack_family = {
        "full_stack",
        "full_stack_without_redblue",
        "full_stack_without_compressor",
        "full_stack_without_memory",
    }
    cfg["evidence"]["verification_enabled"] = system in {"evidence_agent", "full_iterresearch"} or system in full_stack_family
    cfg.setdefault("research", {})["enabled"] = system == "full_iterresearch" or system in full_stack_family
    quality_cfg = cfg.setdefault("quality_control", {})
    is_full_stack = system in full_stack_family
    quality_cfg.update({
        "adversarial_enabled": is_full_stack and system != "full_stack_without_redblue",
        "compression_enabled": is_full_stack and system != "full_stack_without_compressor",
        "memory_enabled": is_full_stack and system != "full_stack_without_memory",
    })
    if is_full_stack:
        cfg["evidence"]["verification_enabled"] = True
        cfg["research"]["enabled"] = True
    if system == "evidence_agent":
        cfg["research"]["max_rounds"] = 1
    return cfg


def _report_failure(report: dict[str, Any]) -> str:
    content = str(report.get("content", "")).strip()
    if not content:
        return "ResearchRunFailed: empty report"
    runtime = report.get("runtime_metrics", {}) or {}
    if runtime.get("partial") or runtime.get("termination_reason") == "global_timeout":
        return (
            "ResearchRunPartial: report terminated before a complete synthesis "
            f"({runtime.get('termination_reason', 'partial')})"
        )
    if content.startswith("Research failed"):
        return f"ResearchRunFailed: {content}"
    return ""


def _record_complete(record: dict[str, Any] | None, judge_enabled: bool) -> bool:
    if record is None or record.get("error") or _report_failure(record.get("report", {})):
        return False
    return not judge_enabled or (
        record.get("report_judge") is not None and not record.get("judge_error")
    )


async def _run_direct(query: str, config: dict[str, Any]) -> ResearchReport:
    sampling = config.get("model", {}).get("backend_sampling", {})
    kwargs = dict(sampling.get("qwen", {}))
    kwargs.update(sampling.get("modules", {}).get("summarizer", {}))
    policy = ModelRouter.create_backend("qwen", fresh_instance=True, **kwargs)
    started = time.monotonic()
    response = await asyncio.to_thread(policy, [
        {"role": "system", "content": (
            "你是 AI 技术研究系统。使用中文直接生成简洁但完整的 Markdown 报告。"
            "不得使用工具或虚构来源；不确定时明确说明。"
        )},
        {"role": "user", "content": (
            f"研究问题：{query}\n\n"
            "统一输出结构：Executive Summary → Scope/As-of Date → Key Findings → "
            "Technical Comparison → Risks/Unknowns → Recommendation → Confidence and Limitations。"
            "事实、分析和不确定性必须分开；不要声称使用了外部来源。"
        )},
    ])
    content = response.get("content", "") or ""
    return ResearchReport(
        query=query, content=content, sources=[],
        claims=EvidencePipeline(verify=False).build_claims(content, []),
        runtime_metrics={"elapsed_seconds": round(time.monotonic() - started, 3),
                         "tool_calls": 0, **response.get("usage", {})},
        verification_applicability=False,
    )


async def _run_one(
    case: dict[str, Any], system: str, base: dict[str, Any], orchestrator_concurrency: int
) -> dict[str, Any]:
    config = _config_for_system(base, system)
    experiment_config = copy.deepcopy(config)
    # Runtime-only throttle: it changes scheduling, not the system capability under test.
    config.setdefault("orchestrator", {})["max_concurrent"] = orchestrator_concurrency
    started = time.monotonic()
    try:
        if system == "direct_llm":
            report = await _run_direct(case["query"], config)
        else:
            report = await run_research_report(
                case["query"], config, initialize_modules(config), close_shared_tools=False
            )
        payload = serialize_report(report)
        error = _report_failure(payload)
    except Exception as exc:
        payload = serialize_report(ResearchReport(query=case["query"], content=f"Research failed: {exc}"))
        error = f"{type(exc).__name__}: {exc}"
    payload.setdefault("runtime_metrics", {})["wall_seconds"] = round(time.monotonic() - started, 3)
    return {
        "report": payload,
        "error": error,
        "config": experiment_config,
        "runtime_overrides": {"orchestrator.max_concurrent": orchestrator_concurrency},
    }


async def _check_urls(
    sources: list[dict[str, Any]], limiter: asyncio.Semaphore
) -> float | None:
    urls = list(dict.fromkeys(str(item.get("url", "")) for item in sources if item.get("url")))
    if not urls:
        return None
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        async def check(url: str) -> bool:
            async with limiter:
                try:
                    async with session.get(url, allow_redirects=True) as response:
                        return bool(response.status < 400)
                except Exception:
                    return False
        values = await asyncio.gather(*(check(url) for url in urls))
    return sum(values) / len(values)


async def _judge_record(
    record: dict[str, Any], judge: DeepSeekJudge, limiter: AdaptiveLimiter,
    url_limiter: asyncio.Semaphore, benchmark_case: dict[str, Any],
) -> None:
    report, query = record["report"], record["report"]["query"]
    async with limiter.slot():
        report_result = await judge.evaluate_report(
            query,
            report["content"],
            context={
                "as_of": benchmark_case.get("as_of"),
                "answerable": benchmark_case.get("answerable", True),
                "expected_topics": benchmark_case.get("expected_topics", []),
                "required_claims": benchmark_case.get("required_claims", []),
                "sources": report.get("sources", []),
                "claims": report.get("claims", []),
            },
        )
    record["report_judge"] = report_result.value
    usage = {**report_result.usage, "elapsed_seconds": round(report_result.elapsed_seconds, 3)}
    claim_results: list[dict[str, Any]] = []
    if report.get("sources"):
        async def judge_claim(claim: dict[str, Any]) -> dict[str, Any]:
            if not claim.get("citations"):
                return {"claim_id": claim.get("claim_id"), "status": "unknown", "confidence": 1.0,
                        "reason": "No citation", "usage": {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}}
            async with limiter.slot():
                result = await judge.evaluate_claim(query, claim, report["sources"])
            return {"claim_id": claim.get("claim_id"), **result.value, "usage": result.usage}

        claim_results = await asyncio.gather(*(judge_claim(claim) for claim in report.get("claims", [])))
        for item in claim_results:
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                usage[key] += int(item.get("usage", {}).get(key, 0))
    record["claim_judgments"] = claim_results
    record["external_evidence_metrics"] = (
        summarize_claim_judgments(report.get("claims", []), claim_results) if report.get("sources") else None
    )
    record["judge_usage"] = usage
    record["url_reachability"] = await _check_urls(report.get("sources", []), url_limiter)


def _add_cost(record: dict[str, Any]) -> None:
    prices = [get_env_float(name, 0.0) for name in (
        "QWEN_INPUT_PRICE_PER_M", "QWEN_OUTPUT_PRICE_PER_M",
        "DEEPSEEK_INPUT_PRICE_PER_M", "DEEPSEEK_OUTPUT_PRICE_PER_M",
    )]
    generation, judgment = record["report"].get("runtime_metrics", {}), record.get("judge_usage", {})
    record["cost"] = {"currency": "CNY", "known": all(value > 0 for value in prices), "amount": None}
    if record["cost"]["known"]:
        record["cost"]["amount"] = round((
            generation.get("input_tokens", 0) * prices[0] + generation.get("output_tokens", 0) * prices[1]
            + judgment.get("input_tokens", 0) * prices[2] + judgment.get("output_tokens", 0) * prices[3]
        ) / 1_000_000, 6)


async def run_cases(args: argparse.Namespace, bench: TechResearchBench) -> None:
    base, output = load_config(args.config), Path(args.output)
    existing = _load_records(output)
    existing_by_key = {item.get("record_key"): item for item in existing}
    model, dataset_hash = get_env("QWEN_MODEL", ""), hashlib.sha256(bench.data_path.read_bytes()).hexdigest()
    pending = []
    for case in bench.get_cases(category=args.category, limit=args.limit):
        for system in args.systems:
            key = f"{case['id']}:{system}:{model}:{_stable_hash(_config_for_system(base, system))}"
            previous = existing_by_key.get(key)
            complete = _record_complete(previous, args.judge)
            if not (args.resume and complete):
                pending.append((case, system, key))
    configure_global_request_limiter(
        args.qwen_concurrency, args.qwen_rpm, args.qwen_initial_concurrency
    )
    lock, case_limiter = asyncio.Lock(), AdaptiveLimiter(args.concurrency)
    judge_limiter = AdaptiveLimiter(args.judge_concurrency)
    url_limiter = asyncio.Semaphore(args.url_concurrency)
    judge = DeepSeekJudge() if args.judge else None

    async def worker(case: dict[str, Any], system: str, key: str) -> None:
        async with case_limiter.slot():
            print(f"[{system}] {case['id']} {case['query'][:55]}")
            result = await _run_one(case, system, base, args.orchestrator_concurrency)
        record = {
            "record_key": key, "case_id": case["id"], "system": system, "model": model,
            "judge_model": get_env("DEEPSEEK_MODEL") if judge else None,
            "config_hash": _stable_hash(result["config"]), "dataset_hash": dataset_hash,
            "runtime_overrides": result["runtime_overrides"] | {
                "case_concurrency": args.concurrency,
                "qwen_concurrency": args.qwen_concurrency,
                "qwen_initial_concurrency": args.qwen_initial_concurrency,
                "qwen_rpm": args.qwen_rpm,
                "judge_concurrency": args.judge_concurrency,
                "url_concurrency": args.url_concurrency,
            },
            "git_commit": _git_commit(), "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "report": result["report"], "evaluation": bench.evaluate_report(result["report"], case["id"]),
            "error": result["error"],
        }
        if judge and not result["error"]:
            try:
                await _judge_record(record, judge, judge_limiter, url_limiter, case)
            except Exception as exc:
                record["judge_error"] = f"{type(exc).__name__}: {exc}"
                if "429" in str(exc):
                    await judge_limiter.halve()
        _add_cost(record)
        async with lock:
            _upsert_record(output, record)

    try:
        await asyncio.gather(*(worker(*item) for item in pending))
    finally:
        await WebSearchTool.close_session()


async def rejudge_records(args: argparse.Namespace, bench: TechResearchBench) -> None:
    """Re-score existing reports without regenerating or searching.

    This separates evaluator changes from generation changes. The updated
    records keep the same ``record_key`` and therefore remain resumable.
    """
    input_path = Path(args.input or args.output)
    output_path = Path(args.output)
    records = _load_records(input_path)
    if not records:
        raise ValueError(f"No benchmark records found: {input_path}")
    judge = DeepSeekJudge()
    limiter = AdaptiveLimiter(args.judge_concurrency)
    url_limiter = asyncio.Semaphore(args.url_concurrency)
    lock = asyncio.Lock()

    async def rejudge(record: dict[str, Any]) -> None:
        case = bench.get_case(str(record["case_id"]))
        record.pop("judge_error", None)
        record.pop("report_judge", None)
        record.pop("claim_judgments", None)
        record.pop("external_evidence_metrics", None)
        record.pop("judge_usage", None)
        record.pop("url_reachability", None)
        try:
            await _judge_record(record, judge, limiter, url_limiter, case)
            record["judge_revision"] = "benchmark_context_v2"
        except Exception as exc:
            record["judge_error"] = f"{type(exc).__name__}: {exc}"
        _add_cost(record)
        async with lock:
            _upsert_record(output_path, record)

    await asyncio.gather(*(rejudge(record) for record in records))


def _summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0}
    ordered = sorted(values)
    return {"n": len(values), "mean": round(statistics.mean(values), 4),
            "median": round(statistics.median(values), 4),
            "stddev": round(statistics.stdev(values), 4) if len(values) > 1 else 0.0,
            "p95": round(ordered[min(len(ordered) - 1, max(0, math.ceil(0.95 * len(ordered)) - 1))], 4)}


def evaluate_records(bench: TechResearchBench, records: list[dict[str, Any]]) -> dict[str, Any]:
    by_system: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        record["evaluation"] = bench.evaluate_report(record["report"], record["case_id"])
        by_system.setdefault(record["system"], []).append(record)
    keys = [record["record_key"] for record in records if record.get("record_key")]
    result: dict[str, Any] = {"systems": {}, "paired_comparisons": {},
                              "resume_key_duplicates": len(keys) - len(set(keys))}
    for system, items in by_system.items():
        valid_items = [item for item in items if not item.get("error")]
        judge_content = [
            float(item["report_judge"]["content_score"])
            for item in valid_items
            if item.get("report_judge") is not None
        ]
        rule_content = [
            float(item["evaluation"]["metrics"].get(
                "content_quality_score", item["evaluation"]["metrics"]["content_score"]
            ))
            for item in valid_items
            if item["evaluation"]["metrics"].get("content_score") is not None
        ]
        latency = [float(item["report"].get("runtime_metrics", {}).get("wall_seconds", 0)) for item in items]
        result["systems"][system] = {
            "runs": len(items), "success_rate": round(sum(
                item["evaluation"]["metrics"]["system_success"] == 1.0 and not item.get("error")
                for item in items
            ) / len(items), 4),
            # Keep content_score as the historical Judge alias for compatibility.
            "content_score": _summary(judge_content or rule_content),
            "judge_content_score": _summary(judge_content),
            "rule_content_score": _summary(rule_content),
            "latency_seconds": _summary(latency),
            "objective": {
                metric: _summary([
                    float(item["evaluation"]["metrics"][metric]) for item in valid_items
                    if item["evaluation"]["metrics"].get(metric) is not None
                ])
                for metric in (
                    "topic_coverage", "reference_claim_recall", "abstention_accuracy",
                    "system_success", "efficiency", "content_quality_score", "content_score",
                )
            },
            "judge_dimensions": {
                dimension: _summary([float(item["report_judge"][dimension]) for item in valid_items
                                     if item.get("report_judge") is not None])
                for dimension in ("factual_accuracy", "comprehensiveness", "analysis_quality",
                                  "presentation", "instruction_following")
            },
            "input_tokens": sum(item["report"].get("runtime_metrics", {}).get("input_tokens", 0) for item in valid_items),
            "output_tokens": sum(item["report"].get("runtime_metrics", {}).get("output_tokens", 0) for item in valid_items),
            "tool_calls": sum(item["report"].get("runtime_metrics", {}).get("tool_calls", 0) for item in valid_items),
            "judge_tokens": sum(item.get("judge_usage", {}).get("total_tokens", 0) for item in valid_items),
            "average_cost_cny": round(statistics.mean([
                item["cost"]["amount"] for item in valid_items if item.get("cost", {}).get("amount") is not None
            ]), 6) if any(item.get("cost", {}).get("amount") is not None for item in valid_items) else None,
            "source": {
                metric: _summary([float(item["evaluation"]["metrics"][metric]) for item in valid_items
                                  if item["evaluation"]["metrics"].get(metric) is not None
                                  and not (system == "direct_llm" and metric in {
                                      "gold_source_recall_at_10", "gold_source_precision_at_10"
                                  })])
                for metric in (
                    "source_quality", "primary_source_rate", "source_diversity",
                    "gold_source_recall_at_10", "gold_source_precision_at_10",
                )
            } | {"url_reachability": _summary([
                float(item["url_reachability"]) for item in valid_items if item.get("url_reachability") is not None
            ])},
            "evidence": {metric: _summary([float(item["external_evidence_metrics"][metric]) for item in valid_items
                                           if item.get("external_evidence_metrics") is not None])
                         for metric in (
                             "citation_coverage", "citation_correctness", "citation_completeness",
                             "unsupported_claim_rate", "unsupported_important_claim_rate",
                             "contradicted_claim_rate",
                         )},
            "adversarial": {
                metric: _summary([
                    float(item["report"].get("runtime_metrics", {}).get(metric))
                    for item in valid_items
                    if item["report"].get("runtime_metrics", {}).get(metric) is not None
                ])
                for metric in (
                    "red_issue_count", "blue_fix_acceptance_rate", "audit_score",
                    "deleted_claim_count", "oscillation_count", "adversarial_rounds",
                )
            },
            "compression": {
                metric: _summary([
                    float(item["report"].get("runtime_metrics", {}).get(metric))
                    for item in valid_items
                    if item["report"].get("runtime_metrics", {}).get(metric) is not None
                ])
                for metric in ("compression_ratio", "evidence_retention")
            },
            "memory": {
                metric: _summary([
                    float(item["report"].get("runtime_metrics", {}).get(metric))
                    for item in valid_items
                    if item["report"].get("runtime_metrics", {}).get(metric) is not None
                ])
                for metric in ("memory_added", "memory_deduplicated", "memory_size")
            },
        }
    for left, right in COMPARISONS:
        left_map = {item["case_id"]: item for item in by_system.get(left, [])}
        right_map = {item["case_id"]: item for item in by_system.get(right, [])}
        common = sorted(
            key for key in set(left_map) & set(right_map)
            if not left_map[key].get("error") and not right_map[key].get("error")
        )
        diffs = [float(right_map[key].get("report_judge", right_map[key]["evaluation"])["content_score"])
                 - float(left_map[key].get("report_judge", left_map[key]["evaluation"])["content_score"])
                 for key in common]
        if diffs:
            stats = bootstrap_ci_paired(diffs)
            stats["cohens_dz"] = round(paired_cohens_dz(diffs), 4)
            result["paired_comparisons"][f"{right}_minus_{left}"] = stats
        dimension_diffs = [
            float(right_map[key]["report_judge"]["comprehensiveness"])
            - float(left_map[key]["report_judge"]["comprehensiveness"])
            for key in common
            if left_map[key].get("report_judge") is not None
            and right_map[key].get("report_judge") is not None
        ]
        if dimension_diffs:
            dimension_stats = bootstrap_ci_paired(dimension_diffs)
            dimension_stats["cohens_dz"] = round(paired_cohens_dz(dimension_diffs), 4)
            result["paired_comparisons"][f"{right}_minus_{left}:comprehensiveness"] = dimension_stats
        for metric in ("topic_coverage", "reference_claim_recall", "abstention_accuracy"):
            objective_diffs = [
                float(right_map[key]["evaluation"]["metrics"][metric])
                - float(left_map[key]["evaluation"]["metrics"][metric])
                for key in common
                if left_map[key]["evaluation"]["metrics"].get(metric) is not None
                and right_map[key]["evaluation"]["metrics"].get(metric) is not None
            ]
            if objective_diffs:
                objective_stats = bootstrap_ci_paired(objective_diffs)
                objective_stats["cohens_dz"] = round(paired_cohens_dz(objective_diffs), 4)
                result["paired_comparisons"][f"{right}_minus_{left}:{metric}"] = objective_stats
        rule_content_diffs = [
            float(right_map[key]["evaluation"]["metrics"].get(
                "content_quality_score", right_map[key]["evaluation"]["metrics"]["content_score"]
            ))
            - float(left_map[key]["evaluation"]["metrics"].get(
                "content_quality_score", left_map[key]["evaluation"]["metrics"]["content_score"]
            ))
            for key in common
            if left_map[key]["evaluation"]["metrics"].get("content_score") is not None
            and right_map[key]["evaluation"]["metrics"].get("content_score") is not None
        ]
        if rule_content_diffs:
            rule_stats = bootstrap_ci_paired(rule_content_diffs)
            rule_stats["cohens_dz"] = round(paired_cohens_dz(rule_content_diffs), 4)
            result["paired_comparisons"][f"{right}_minus_{left}:rule_content_score"] = rule_stats
        for metric in ("citation_correctness", "unsupported_claim_rate"):
            evidence_diffs = [
                float(right_map[key]["external_evidence_metrics"][metric])
                - float(left_map[key]["external_evidence_metrics"][metric])
                for key in common
                if left_map[key].get("external_evidence_metrics") is not None
                and right_map[key].get("external_evidence_metrics") is not None
            ]
            if evidence_diffs:
                evidence_stats = bootstrap_ci_paired(evidence_diffs)
                evidence_stats["cohens_dz"] = round(paired_cohens_dz(evidence_diffs), 4)
                result["paired_comparisons"][f"{right}_minus_{left}:{metric}"] = evidence_stats
    return result


def render_report(summary: dict[str, Any]) -> str:
    total_runs = sum(int(item.get("runs", 0)) for item in summary.get("systems", {}).values())
    successful_runs = sum(
        int(round(float(item.get("runs", 0)) * float(item.get("success_rate", 0.0))))
        for item in summary.get("systems", {}).values()
    )
    is_formal_30x4 = total_runs >= 120
    report_title = (
        "# TechResearchBench-Mini Formal Evaluation Report"
        if is_formal_30x4
        else "# TechResearchBench-Mini Calibration Evaluation Report"
    )
    report_note = (
        f"> 当前汇总包含 {total_runs} 条系统记录，其中 {successful_runs} 条成功完成；"
        "这是 30 题 × 4 系统的正式冻结协议结果。"
        if is_formal_30x4
        else f"> 当前汇总包含 {total_runs} 条系统记录；用于接口和指标校准，不等同于正式 30 题 benchmark。"
    )
    lines = [
             report_title, "",
             report_note, "",
             "## 系统结果", "", "| 系统 | Runs | Success | Judge Content | Rule Content | P95 latency | Judge tokens | Avg cost |",
             "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for system in SYSTEMS:
        item = summary.get("systems", {}).get(system, {})
        if not item:
            continue
        cost = item.get("average_cost_cny")
        lines.append(
            f"| {system} | {item['runs']} | {item['success_rate']:.1%} | "
            f"{item.get('judge_content_score', item['content_score']).get('mean', 0):.2f} | "
            f"{item.get('rule_content_score', {}).get('mean', 0):.2f} | "
            f"{item['latency_seconds'].get('p95', 0):.2f}s | "
            f"{item.get('judge_tokens', 0)} | {cost if cost is not None else 'N/A'} |"
        )
    lines.extend([
        "", "## 客观指标", "",
        "| 系统 | Topic coverage | Reference claim recall | Abstention accuracy | Rule content | Gold source R@10 | Primary source rate | Citation coverage | Citation correctness | Unsupported claim rate |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for system in SYSTEMS:
        item = summary.get("systems", {}).get(system, {})
        if not item:
            continue

        def mean(group: str, metric: str) -> str:
            value = item.get(group, {}).get(metric, {}).get("mean")
            return f"{value:.3f}" if value is not None else "N/A"

        lines.append(
            f"| {system} | {mean('objective', 'topic_coverage')} | "
            f"{mean('objective', 'reference_claim_recall')} | "
            f"{mean('objective', 'abstention_accuracy')} | "
            f"{mean('objective', 'content_score')} | "
            f"{mean('source', 'gold_source_recall_at_10')} | "
            f"{mean('source', 'primary_source_rate')} | "
            f"{mean('evidence', 'citation_coverage')} | "
            f"{mean('evidence', 'citation_correctness')} | "
            f"{mean('evidence', 'unsupported_claim_rate')} |"
        )
    lines.extend(["", "## 配对比较", "", "| 比较 | Mean diff | 95% CI | Cohen's dz | 结论 |",
                  "|---|---:|---:|---:|---|"])
    for name, item in summary.get("paired_comparisons", {}).items():
        if item.get("insufficient_n"):
            conclusion = "样本不足，不能判断显著性"
        else:
            significant = item.get(
                "significant",
                item.get("ci_lower", 0) > 0 or item.get("ci_upper", 0) < 0,
            )
            if significant and item.get("ci_lower", 0) > 0:
                conclusion = "显著提升"
            elif significant and item.get("ci_upper", 0) < 0:
                conclusion = "显著下降"
            elif item.get("mean_diff", 0) > 0:
                conclusion = "提升趋势/无显著差异"
            elif item.get("mean_diff", 0) < 0:
                conclusion = "下降趋势/无显著差异"
            else:
                conclusion = "无差异"
        lines.append(f"| {name} | {item['mean_diff']:.4f} | [{item['ci_lower']:.4f}, {item['ci_upper']:.4f}] | "
                     f"{item.get('cohens_dz', 0):.4f} | {conclusion} |")
    lines.extend(["", "## 简历填写规则", "", "仅使用四系统成对完成的数据。CI 跨越 0 时写“观察到提升趋势”，"
                  "不得写“显著提升”。成本为 N/A 时先在 `.env.local` 配置每百万 tokens 单价后重新聚合。", ""])
    return "\n".join(lines)


def _markdown_report_content(record: dict[str, Any]) -> str:
    report = record.get("report", {})
    content = str(report.get("content", "")).strip()
    if not content:
        content = "[empty report]"
    return content + "\n"


def _render_case_comparison(case: dict[str, Any], records: list[dict[str, Any]]) -> str:
    by_system = {record.get("system"): record for record in records}
    lines = [
        f"# {case.get('id')} 四系统报告对比",
        "",
        f"**问题：** {case.get('query', '')}",
        f"**As-of：** {case.get('as_of', 'N/A')}",
        f"**可回答性：** {case.get('answerable', True)}",
        "",
        "## 运行与指标",
        "",
        "| 系统 | 成功 | 字符数 | 来源数 | Claim 数 | Rule content | Judge content | Citation coverage | Citation correctness | Unsupported claim rate | 错误 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for system in SYSTEMS:
        record = by_system.get(system)
        if not record:
            continue
        report = record.get("report", {})
        metrics = record.get("evaluation", {}).get("metrics", {})
        evidence = record.get("external_evidence_metrics") or {}
        judge = record.get("report_judge") or {}
        def fmt(value: Any, digits: int = 3) -> str:
            if value is None:
                return "N/A"
            if isinstance(value, float):
                return f"{value:.{digits}f}"
            return str(value)
        lines.append(
            f"| {system} | {fmt(metrics.get('system_success'))} | "
            f"{len(str(report.get('content', '')))} | {len(report.get('sources', []))} | "
            f"{len(report.get('claims', []))} | {fmt(metrics.get('content_score'))} | "
            f"{fmt(judge.get('content_score'))} | {fmt(evidence.get('citation_coverage'))} | "
            f"{fmt(evidence.get('citation_correctness'))} | {fmt(evidence.get('unsupported_claim_rate'))} | "
            f"{record.get('error') or record.get('judge_error') or ''} |"
        )
    lines.extend([
        "",
        "## 参考标注",
        "",
        f"- Expected topics: {', '.join(case.get('expected_topics', [])) or 'N/A'}",
        f"- Required claims: {', '.join(case.get('required_claims', [])) or 'N/A'}",
        f"- Gold source patterns: {', '.join(case.get('gold_source_patterns', [])) or 'N/A'}",
        "",
        "## Judge 理由",
        "",
    ])
    for system in SYSTEMS:
        record = by_system.get(system)
        if record and record.get("report_judge"):
            lines.append(f"### {system}")
            lines.append("")
            lines.append(str(record["report_judge"].get("reason", "N/A")))
            lines.append("")
    lines.extend([
        "## 人工复核",
        "",
        "- 抽检 Claim：",
        "- Judge 与人工一致性：",
        "- 主要退化原因：",
        "- 可复现备注：",
        "",
    ])
    return "\n".join(lines)


def write_report_comparison(
    records: list[dict[str, Any]], bench: TechResearchBench, output_dir: str | Path,
) -> None:
    """Write per-case reports and a human-reviewable comparison package."""
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record.get("case_id")), []).append(record)
    index_lines = [
        "# TechResearchBench-Mini 报告对照包", "",
        "本目录保存每道题四个系统的原始报告、结构化指标和人工复核栏。",
        "Judge 分数不是事实真值；请同时检查规则指标、来源和 Claim–Evidence 状态。", "",
    ]
    for case_id, case_records in sorted(grouped.items()):
        case_dir = root / case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        case = bench.get_case(case_id)
        for record in case_records:
            system = str(record.get("system"))
            (case_dir / f"{system}.md").write_text(_markdown_report_content(record), encoding="utf-8")
        (case_dir / "metrics.json").write_text(
            json.dumps(case_records, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (case_dir / "comparison.md").write_text(
            _render_case_comparison(case, case_records), encoding="utf-8"
        )
        index_lines.append(f"- [{case_id}]({case_id}/comparison.md)")
    (root / "README.md").write_text("\n".join(index_lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Resumable AI Technology Research Agent benchmark")
    parser.add_argument("--mode", choices=["run", "rejudge", "evaluate"], default="evaluate")
    parser.add_argument("--output", default="outputs/tech_benchmark/results.jsonl")
    parser.add_argument("--input", default=None, help="Existing JSONL used in evaluate mode")
    parser.add_argument("--summary", default="outputs/tech_benchmark/summary.json")
    parser.add_argument("--report", default="outputs/tech_benchmark/PILOT_REPORT.md")
    parser.add_argument("--comparison-dir", default=None,
                        help="Write per-case report comparison package to this directory")
    parser.add_argument("--config", default=None)
    parser.add_argument("--category", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--systems", nargs="+", choices=SYSTEMS, default=list(DEFAULT_SYSTEMS))
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--orchestrator-concurrency", type=int, default=3)
    parser.add_argument("--qwen-concurrency", type=int, default=12)
    parser.add_argument("--qwen-initial-concurrency", type=int, default=None)
    parser.add_argument("--qwen-rpm", type=int, default=600)
    parser.add_argument("--judge-concurrency", type=int, default=16)
    parser.add_argument("--url-concurrency", type=int, default=20)
    parser.add_argument("--judge", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--resume", action=argparse.BooleanOptionalAction, default=True)
    args = parser.parse_args()
    bench = TechResearchBench()
    if args.mode == "run":
        asyncio.run(run_cases(args, bench))
    elif args.mode == "rejudge":
        asyncio.run(rejudge_records(args, bench))
    records_path = Path(args.output) if args.mode == "rejudge" else Path(args.input or args.output)
    records = _load_records(records_path)
    if not records:
        parser.error(f"No benchmark records found: {records_path}")
    result = evaluate_records(bench, records)
    path = Path(args.summary)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    report_path = Path(args.report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(result), encoding="utf-8")
    if args.comparison_dir:
        write_report_comparison(records, bench, args.comparison_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
