"""Three-stage JSON parsing fallback for structured agent responses."""
from __future__ import annotations

import json
import re
from typing import Any


def _balanced_objects(text: str) -> list[str]:
    candidates: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{" and depth == 0:
            start = index
            depth = 1
        elif char == "{" and depth > 0:
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : index + 1])
                start = None
    return candidates


def parse_json_with_fallback(text: str) -> tuple[dict[str, Any], str]:
    cleaned = re.sub(r"<think>.*?</think>|</?think>", "", text, flags=re.DOTALL | re.I).strip()

    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.I).strip()
    try:
        value = json.loads(fenced)
        if isinstance(value, dict):
            return value, "plain_or_fenced"
    except (json.JSONDecodeError, TypeError):
        pass

    for candidate in _balanced_objects(cleaned):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value, "balanced_object"
        except (json.JSONDecodeError, TypeError):
            continue

    match = re.search(
        r"(?:json\s*[:：]\s*|response\s*[:：]\s*)(\{.*\})",
        cleaned,
        flags=re.I | re.S,
    )
    if match:
        try:
            value = json.loads(match.group(1))
            if isinstance(value, dict):
                return value, "prefixed_object"
        except json.JSONDecodeError:
            pass
    raise ValueError("Response does not contain a valid JSON object")
