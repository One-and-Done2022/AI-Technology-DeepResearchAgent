#!/usr/bin/env python3
"""Replay quality modules on a fixed generated report and source trace.

This script deliberately performs no model or search calls.  It is used to
separate post-processing effects (Evidence, Red-Blue, compression, memory)
from fresh Qwen/search randomness.  The input should contain at least one
record per case for ``--base-system`` (normally ``search_agent``).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from pathlib import Path
from typing import Any

from evaluation.benchmarks.tech_research_bench import TechResearchBench
from src.adversarial import RedBlueAuditor
from src.compressor import EvidencePreservingCompressor
from src.evidence.extractor import EvidencePipeline
from src.memory import EvidenceMemory


REPLAY_SYSTEMS = (
    "search_replay",
    "evidence_replay",
    "redblue_replay",
    "compressor_replay",
    "memory_replay",
    "full_replay",
)


def _load_records(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 6) if values else None


def _build_replay_report(
    base: dict[str, Any], system: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    original = dict(base.get("report", {}))
    content = str(original.get("content", ""))
    sources = list(original.get("sources", []))
    pipeline = EvidencePipeline(verify=system != "search_replay")
    claims = pipeline.build_claims(content, sources)
    runtime = dict(original.get("runtime_metrics", {}))
    runtime.update({
        "replay": True,
        "replay_base_system": base.get("system"),
        "replay_generation_calls": 0,
        "replay_search_calls": 0,
    })

    if system in {"compressor_replay", "full_replay"}:
        compressor = EvidencePreservingCompressor()
        compressed = compressor.compress(content, claims)
        content = compressed.text
        runtime.update(compressed.metrics())

    if system in {"redblue_replay", "full_replay"}:
        audit = RedBlueAuditor(max_rounds=2, expose_audit=False).audit(content, claims)
        content = audit.content
        claims = audit.claims
        runtime.update(audit.metrics())

    if system in {"memory_replay", "full_replay"}:
        memory = EvidenceMemory()
        runtime.update(memory.add_sources(sources))
        runtime["memory_replay_only"] = True

    replay_report = {
        "query": original.get("query", ""),
        "content": content,
        "sources": sources,
        "claims": claims,
        "runtime_metrics": runtime,
        "verification_applicability": True,
        "replay_of": base.get("record_key"),
    }
    return replay_report, runtime


def _summary(bench: TechResearchBench, records: list[dict[str, Any]]) -> dict[str, Any]:
    systems: dict[str, dict[str, Any]] = {}
    for system in REPLAY_SYSTEMS:
        items = [item for item in records if item["system"] == system]
        metrics = [item["evaluation"]["metrics"] for item in items]
        systems[system] = {
            "runs": len(items),
            "objective": {
                name: _mean([float(metric[name]) for metric in metrics if metric.get(name) is not None])
                for name in (
                    "topic_coverage", "reference_claim_recall", "abstention_accuracy",
                    "content_quality_score",
                )
            },
            "evidence": {
                name: _mean([
                    float(metric[name]) for metric in metrics if metric.get(name) is not None
                ])
                for name in (
                    "citation_coverage", "citation_entailment", "unsupported_claim_rate",
                    "contradicted_claim_rate",
                )
            },
            "runtime": {
                name: _mean([
                    float(item["report"].get("runtime_metrics", {}).get(name))
                    for item in items
                    if item["report"].get("runtime_metrics", {}).get(name) is not None
                ])
                for name in ("compression_ratio", "evidence_retention", "memory_deduplicated")
            },
        }

    by_case = {
        system: {item["case_id"]: item for item in records if item["system"] == system}
        for system in REPLAY_SYSTEMS
    }
    pairwise: dict[str, dict[str, Any]] = {}
    for left, right in (
        ("search_replay", "evidence_replay"),
        ("evidence_replay", "redblue_replay"),
        ("evidence_replay", "compressor_replay"),
        ("evidence_replay", "memory_replay"),
        ("evidence_replay", "full_replay"),
    ):
        common = sorted(set(by_case[left]) & set(by_case[right]))
        for metric_group, metric_names in (
            ("objective", ("content_score", "topic_coverage", "reference_claim_recall")),
            ("evidence", ("citation_entailment", "unsupported_claim_rate")),
        ):
            for name in metric_names:
                diffs = []
                for case_id in common:
                    a = by_case[left][case_id]["evaluation"]["metrics"].get(name)
                    b = by_case[right][case_id]["evaluation"]["metrics"].get(name)
                    if a is not None and b is not None:
                        diffs.append(float(b) - float(a))
                if diffs:
                    pairwise[f"{right}_minus_{left}:{name}"] = {
                        "n": len(diffs),
                        "mean_diff": round(statistics.mean(diffs), 6),
                        "diffs": [round(value, 6) for value in diffs],
                    }
    return {
        "protocol": "fixed_trace_postprocessing_replay",
        "generation_calls": 0,
        "search_calls": 0,
        "systems": systems,
        "paired_comparisons": pairwise,
        "dataset_hash": hashlib.sha256(bench.data_path.read_bytes()).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="JSONL containing generated benchmark records")
    parser.add_argument("--output", required=True, help="Output JSONL for replay records")
    parser.add_argument("--summary", required=True, help="Output summary JSON")
    parser.add_argument("--base-system", default="search_agent")
    args = parser.parse_args()

    input_path, output_path, summary_path = map(Path, (args.input, args.output, args.summary))
    source_records = _load_records(input_path)
    base_by_case: dict[str, dict[str, Any]] = {}
    for record in source_records:
        if record.get("system") == args.base_system and record.get("case_id") not in base_by_case:
            base_by_case[str(record["case_id"])] = record
    if not base_by_case:
        raise SystemExit(f"No records found for base system: {args.base_system}")

    bench = TechResearchBench()
    replay_records: list[dict[str, Any]] = []
    for case_id, base in sorted(base_by_case.items()):
        for system in REPLAY_SYSTEMS:
            report, _ = _build_replay_report(base, system)
            evaluation = bench.evaluate_report(report, case_id)
            replay_records.append({
                "record_key": f"replay:{case_id}:{system}:{base.get('record_key')}",
                "case_id": case_id,
                "system": system,
                "base_system": args.base_system,
                "base_record_key": base.get("record_key"),
                "report": report,
                "evaluation": evaluation,
                "error": None,
            })

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for record in replay_records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = _summary(bench, replay_records)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
