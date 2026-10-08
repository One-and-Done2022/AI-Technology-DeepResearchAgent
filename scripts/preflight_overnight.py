#!/usr/bin/env python3
"""Validate model, judge, and search configuration before an overnight pilot."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.judge import DeepSeekJudge
from src.models.model_router import ModelRouter
from src.tools.web_search import WebSearchTool
from src.utils.env_config import get_env


async def main() -> int:
    checks: dict[str, dict] = {}
    try:
        policy = ModelRouter.create_backend("qwen", fresh_instance=True, max_tokens=16, temperature=0)
        response = await asyncio.to_thread(policy, [{"role": "user", "content": "Reply exactly: OK"}])
        checks["qwen"] = {"ok": response.get("content", "").strip() == "OK", "model": policy.model_name,
                          "usage": response.get("usage", {})}
    except Exception as exc:
        checks["qwen"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    try:
        judge = DeepSeekJudge()
        response = await judge.evaluate_report("什么是 Transformer？", "Transformer 是一种神经网络架构。")
        checks["judge"] = {"ok": 0 <= response.value["content_score"] <= 10,
                           "model": judge.model, "usage": response.usage}
    except Exception as exc:
        checks["judge"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    backend = get_env("SEARCH_BACKEND", "serpapi")
    required_key = {"bocha": "BOCHA_API_KEY", "bing": "BING_SEARCH_KEY",
                    "serpapi": "SERPAPI_KEY", "metaso": "METASO_API_KEY"}.get(backend or "")
    if backend == "openalex":
        required_key = None
    if backend not in {"openalex", "bocha", "bing", "serpapi", "metaso"} or (required_key and not get_env(required_key)):
        checks["search"] = {"ok": False, "backend": backend,
                            "error": f"Missing {required_key or 'supported SEARCH_BACKEND'}"}
    else:
        try:
            result = await WebSearchTool().execute("Transformer official paper", top_n=1)
            checks["search"] = {"ok": bool(result.get("results")), "backend": backend,
                                "result_count": len(result.get("results", [])), "error": result.get("error")}
        except Exception as exc:
            checks["search"] = {"ok": False, "backend": backend,
                                "error": f"{type(exc).__name__}: {exc}"}
        finally:
            await WebSearchTool.close_session()
    checks["ready"] = {"ok": all(checks[name]["ok"] for name in ("qwen", "judge", "search"))}
    print(json.dumps(checks, ensure_ascii=False, indent=2))
    return 0 if checks["ready"]["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
