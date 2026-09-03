"""Domain benchmark for AI, software systems, and open-source research."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evaluation.metrics.claim_metrics import ClaimMetrics


DEFAULT_DATASET = Path(__file__).resolve().parent.parent / "datasets" / "tech_research_mini.jsonl"


class TechResearchBench:
    def __init__(self, data_path: str | None = None) -> None:
        self.data_path = Path(data_path) if data_path else DEFAULT_DATASET
        self.cases = self._load(self.data_path)
        self._by_id = {case["id"]: case for case in self.cases}

    @staticmethod
    def _load(path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            raise FileNotFoundError(f"TechResearchBench dataset not found: {path}")
        cases: list[dict[str, Any]] = []
        seen: set[str] = set()
        with path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                case = json.loads(line)
                case_id = str(case.get("id", ""))
                if not case_id or case_id in seen:
                    raise ValueError(f"Invalid or duplicate case id at line {line_no}: {case_id}")
                seen.add(case_id)
                cases.append(case)
        return cases

    def get_cases(
        self,
        category: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        result = self.cases
        if category:
            result = [case for case in result if case.get("category") == category]
        return result[:limit] if limit is not None else list(result)

    def get_case(self, case_id: str) -> dict[str, Any]:
        try:
            return self._by_id[case_id]
        except KeyError as exc:
            raise ValueError(f"Unknown TechResearchBench case: {case_id}") from exc

    def evaluate_report(self, report: Any, case_id: str) -> dict[str, Any]:
        case = self.get_case(case_id)
        metrics = ClaimMetrics.evaluate(
            report,
            expected_topics=case.get("expected_topics", []),
            required_claims=case.get("required_claims", []),
            answerable=bool(case.get("answerable", True)),
        )
        return {
            "case_id": case_id,
            "category": case.get("category", ""),
            "difficulty": case.get("difficulty", ""),
            "metrics": metrics,
            "composite_score": metrics["composite_score"],
        }

    @staticmethod
    def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
        if not results:
            return {"num_cases": 0, "averages": {}, "by_category": {}}
        metric_names = sorted(
            {
                metric
                for result in results
                for metric in result.get("metrics", {})
            }
        )
        averages = {
            metric: sum(result["metrics"].get(metric, 0.0) for result in results) / len(results)
            for metric in metric_names
        }
        by_category: dict[str, dict[str, float]] = {}
        categories = sorted({result.get("category", "") for result in results})
        for category in categories:
            selected = [result for result in results if result.get("category") == category]
            by_category[category] = {
                metric: sum(item["metrics"].get(metric, 0.0) for item in selected) / len(selected)
                for metric in metric_names
            }
        return {
            "num_cases": len(results),
            "averages": {key: round(value, 6) for key, value in averages.items()},
            "by_category": {
                category: {key: round(value, 6) for key, value in metrics.items()}
                for category, metrics in by_category.items()
            },
        }
