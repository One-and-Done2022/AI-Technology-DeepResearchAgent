#!/usr/bin/env python3
"""Run or score TechResearchBench with reproducible structured outputs."""
from __future__ import annotations

import argparse
import asyncio
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.benchmarks.tech_research_bench import TechResearchBench
from evaluation.metrics.stats import bootstrap_ci_paired
from src.core.runner import initialize_modules, load_config, run_research_report, serialize_report
from src.orchestrator.schemas import ResearchReport


def _load_records(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def _save_records(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


async def _run_direct(query: str, modules: dict[str, Any]) -> ResearchReport:
    policy = modules["default_policy"]
    started = time.monotonic()
    response = await asyncio.to_thread(
        policy,
        [
            {
                "role": "system",
                "content": (
                    "Answer the AI technology research question directly in Chinese. "
                    "Do not use tools. State uncertainty instead of inventing sources."
                ),
            },
            {"role": "user", "content": query},
        ],
    )
    content = response.get("content", "") or ""
    return ResearchReport(
        query=query,
        content=content,
        runtime_metrics={
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "tool_calls": 0,
            "token_usage": len(content) // 3,
        },
    )


def _config_for_system(base: dict[str, Any], system: str) -> dict[str, Any]:
    cfg = copy.deepcopy(base)
    if system == "single_round":
        cfg.setdefault("research", {})["enabled"] = False
    elif system == "evidence":
        cfg.setdefault("research", {})["enabled"] = True
    return cfg


async def run_cases(
    bench: TechResearchBench,
    cases: list[dict[str, Any]],
    systems: list[str],
    config_path: str | None,
) -> list[dict[str, Any]]:
    base_config = load_config(config_path)
    records: list[dict[str, Any]] = []
    for system in systems:
        config = _config_for_system(base_config, system)
        modules = initialize_modules(config)
        for index, case in enumerate(cases, 1):
            print(f"[{system}] {index}/{len(cases)} {case['id']}: {case['query'][:60]}")
            try:
                if system == "direct":
                    report = await _run_direct(case["query"], modules)
                else:
                    report = await run_research_report(case["query"], config, modules)
                payload = serialize_report(report)
                error = ""
            except Exception as exc:
                payload = serialize_report(
                    ResearchReport(query=case["query"], content=f"Research failed: {exc}")
                )
                error = f"{type(exc).__name__}: {exc}"
            score = bench.evaluate_report(payload, case["id"])
            records.append(
                {
                    "case_id": case["id"],
                    "system": system,
                    "report": payload,
                    "evaluation": score,
                    "error": error,
                }
            )
    return records


def evaluate_records(bench: TechResearchBench, records: list[dict[str, Any]]) -> dict[str, Any]:
    rescored: list[dict[str, Any]] = []
    by_system: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        evaluation = bench.evaluate_report(record["report"], record["case_id"])
        record["evaluation"] = evaluation
        rescored.append(record)
        by_system.setdefault(record.get("system", "unknown"), []).append(evaluation)

    summary: dict[str, Any] = {
        "systems": {
            system: bench.summarize(evaluations)
            for system, evaluations in by_system.items()
        },
        "paired_comparisons": {},
    }
    systems = sorted(by_system)
    for left_index, left in enumerate(systems):
        left_scores = {
            item["case_id"]: item["composite_score"] for item in by_system[left]
        }
        for right in systems[left_index + 1 :]:
            right_scores = {
                item["case_id"]: item["composite_score"] for item in by_system[right]
            }
            common = sorted(set(left_scores) & set(right_scores))
            if len(common) < 2:
                continue
            diffs = [right_scores[case_id] - left_scores[case_id] for case_id in common]
            summary["paired_comparisons"][f"{right}_minus_{left}"] = bootstrap_ci_paired(diffs)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Technology Research Agent benchmark")
    parser.add_argument("--mode", choices=["run", "evaluate"], default="evaluate")
    parser.add_argument("--input", type=str, help="Existing JSONL records for evaluate mode")
    parser.add_argument("--output", type=str, default="outputs/tech_benchmark/results.jsonl")
    parser.add_argument("--summary", type=str, default="outputs/tech_benchmark/summary.json")
    parser.add_argument("--config", type=str, default=None)
    parser.add_argument("--category", type=str, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--systems",
        nargs="+",
        choices=["direct", "single_round", "evidence"],
        default=["direct", "single_round", "evidence"],
    )
    args = parser.parse_args()

    bench = TechResearchBench()
    output_path = Path(args.output)
    if args.mode == "run":
        cases = bench.get_cases(category=args.category, limit=args.limit)
        records = asyncio.run(run_cases(bench, cases, args.systems, args.config))
        _save_records(output_path, records)
    else:
        input_path = Path(args.input) if args.input else output_path
        if not input_path.exists():
            parser.error(f"No benchmark records found: {input_path}. Run with --mode run first.")
        records = _load_records(input_path)

    summary = evaluate_records(bench, records)
    summary_path = Path(args.summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"records={output_path} summary={summary_path}")


if __name__ == "__main__":
    main()
