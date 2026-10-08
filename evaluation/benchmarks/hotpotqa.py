"""HotpotQA-style evaluation adapter with exact match, F1 and coverage."""
from __future__ import annotations

import json
import re
import string
from collections import Counter
from pathlib import Path
from typing import Any


MOCK_QUESTIONS = [
    {"id": "hotpot_001", "question": "Who wrote Pride and Prejudice?", "answer": "Jane Austen"},
    {"id": "hotpot_002", "question": "What is the capital of France?", "answer": "Paris"},
    {"id": "hotpot_003", "question": "What planet is known as the Red Planet?", "answer": "Mars"},
    {"id": "hotpot_004", "question": "What language is primarily used for Python package installation?", "answer": "Python"},
    {"id": "hotpot_005", "question": "What does CPU stand for?", "answer": "central processing unit"},
]


def _normalize(text: str) -> str:
    text = text.lower()
    text = "".join(char for char in text if char not in string.punctuation)
    text = re.sub(r"\b(a|an|the)\b", " ", text)
    return " ".join(text.split())


class HotpotQABenchmark:
    def __init__(self, data: list[dict[str, Any]] | None = None, use_mock: bool = False) -> None:
        self.data = list(data or (MOCK_QUESTIONS if use_mock else []))
        self._by_id = {item["id"]: item for item in self.data}

    @classmethod
    def from_json(cls, path: str | Path) -> "HotpotQABenchmark":
        records = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(records, dict):
            records = records.get("data", [])
        return cls(data=records)

    def get_questions(self, n: int | None = None) -> list[dict[str, Any]]:
        """Return the loaded questions for parity with the other adapters."""
        return self.data[:n] if n is not None else list(self.data)

    def get_question(self, question_id: str) -> dict[str, Any]:
        if question_id not in self._by_id:
            raise ValueError(f"Unknown HotpotQA question: {question_id}")
        return self._by_id[question_id]

    @staticmethod
    def exact_match(prediction: str, gold: str) -> float:
        return float(_normalize(prediction) == _normalize(gold))

    @staticmethod
    def f1_score(prediction: str, gold: str) -> float:
        pred_tokens = _normalize(prediction).split()
        gold_tokens = _normalize(gold).split()
        if not pred_tokens or not gold_tokens:
            return float(pred_tokens == gold_tokens)
        common = Counter(pred_tokens) & Counter(gold_tokens)
        overlap = sum(common.values())
        if not overlap:
            return 0.0
        precision = overlap / len(pred_tokens)
        recall = overlap / len(gold_tokens)
        return 2 * precision * recall / (precision + recall)

    @staticmethod
    def pass_at_k(predictions: list[str], gold: str, k: int = 1) -> float:
        return float(any(HotpotQABenchmark.exact_match(prediction, gold) for prediction in predictions[:k]))

    @staticmethod
    def gold_entity_coverage(report: str, gold: str) -> float:
        gold_tokens = set(_normalize(gold).split())
        report_tokens = set(_normalize(report).split())
        return len(gold_tokens & report_tokens) / len(gold_tokens) if gold_tokens else 1.0

    @staticmethod
    def _answer_from_report(report: Any) -> str:
        if isinstance(report, dict):
            if report.get("answer"):
                return str(report["answer"])
            report = report.get("content", "")
        text = str(report)
        match = re.search(r"(?:final answer|答案|answer)\s*[:：]\s*(.+)", text, flags=re.I)
        return match.group(1).strip() if match else text.strip().splitlines()[0] if text.strip() else ""

    def evaluate(self, prediction: Any, question_id: str) -> dict[str, Any]:
        if question_id not in self._by_id:
            raise ValueError(f"Unknown HotpotQA question: {question_id}")
        item = self._by_id[question_id]
        answer = self._answer_from_report(prediction)
        gold = str(item.get("answer", ""))
        return {
            "question_id": question_id,
            "exact_match": self.exact_match(answer, gold),
            "f1": self.f1_score(answer, gold),
            "pass_at_1": self.pass_at_k([answer], gold, k=1),
            "gold_entity_coverage": self.gold_entity_coverage(str(prediction), gold),
        }

