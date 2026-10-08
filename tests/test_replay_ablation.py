from __future__ import annotations

import json

from scripts.replay_ablation import main


def test_fixed_trace_replay_does_not_call_generation(monkeypatch, tmp_path) -> None:
    source = tmp_path / "records.jsonl"
    source.write_text(json.dumps({
        "record_key": "base-1",
        "case_id": "aiml_001",
        "system": "search_agent",
        "report": {
            "query": "解释 Transformer 自注意力",
            "content": "标准全局自注意力相对于序列长度具有平方级复杂度。[S1]",
            "sources": [{
                "source_id": "S1",
                "url": "https://arxiv.org/abs/1706.03762",
                "title": "Attention Is All You Need",
                "quote": "Self-attention has quadratic complexity in sequence length.",
                "source_type": "paper",
                "quality_score": 1.0,
            }],
            "runtime_metrics": {"elapsed_seconds": 1.0, "tool_calls": 1},
        },
    }, ensure_ascii=False) + "\n", encoding="utf-8")
    output = tmp_path / "replay.jsonl"
    summary = tmp_path / "summary.json"
    monkeypatch.setattr(
        "sys.argv",
        ["replay_ablation.py", "--input", str(source), "--output", str(output), "--summary", str(summary)],
    )
    main()
    rows = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 6
    assert {row["system"] for row in rows} == {
        "search_replay", "evidence_replay", "redblue_replay",
        "compressor_replay", "memory_replay", "full_replay",
    }
    assert all(row["report"]["runtime_metrics"]["replay_generation_calls"] == 0 for row in rows)
    summary_data = json.loads(summary.read_text(encoding="utf-8"))
    assert summary_data["protocol"] == "fixed_trace_postprocessing_replay"
    assert summary_data["generation_calls"] == 0
