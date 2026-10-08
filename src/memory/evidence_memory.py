"""Small shared evidence index used by research runs and ablations."""
from __future__ import annotations

import hashlib
from typing import Any

import numpy as np


class EvidenceMemory:
    def __init__(self, dimension: int = 64) -> None:
        self.dimension = max(8, int(dimension))
        self._items: dict[str, dict[str, Any]] = {}
        self._vectors: dict[str, np.ndarray] = {}

    def _vector(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0
        norm = np.linalg.norm(vector)
        return vector / norm if norm else vector

    def add_sources(self, sources: list[dict[str, Any]]) -> dict[str, int]:
        added = 0
        deduplicated = 0
        for source in sources:
            key = str(source.get("content_hash") or source.get("url") or "")
            if not key:
                continue
            if key in self._items:
                deduplicated += 1
                continue
            payload = dict(source)
            self._items[key] = payload
            self._vectors[key] = self._vector(
                f"{payload.get('title', '')} {payload.get('quote', payload.get('snippet', ''))}"
            )
            added += 1
        return {"memory_added": added, "memory_deduplicated": deduplicated, "memory_size": len(self._items)}

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        query_vector = self._vector(query)
        scored = []
        for key, vector in self._vectors.items():
            scored.append((float(np.dot(query_vector, vector)), self._items[key]))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [dict(item, memory_similarity=round(score, 4)) for score, item in scored[:top_k]]

    def clear(self) -> None:
        self._items.clear()
        self._vectors.clear()
