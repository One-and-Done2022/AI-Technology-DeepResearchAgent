# Formal Benchmark 当前运行状态

## 当前状态（已收口）

- 实验：`TechResearchBench-Mini` 30 题 × 4 系统
- 目标记录：120
- 已落盘：120/120
- 生成成功：119/120
- 已落盘记录中的 Judge 错误：0
- 生成模型：`Qwen/Qwen2.5-7B-Instruct`
- Judge：`deepseek-ai/DeepSeek-V4-Flash`
- 搜索后端：`OpenAlex`
- 运行配置：`configs/benchmark.yaml`
- 输出目录：[outputs/tech_benchmark_openalex_formal_current](/home/liuchenyang/deepresearch-agent/outputs/tech_benchmark_openalex_formal_current)

## 运行命令

```bash
SEARCH_BACKEND=openalex PYTHONPATH=. .venv/bin/python scripts/run_tech_benchmark.py \
  --mode run \
  --limit 30 \
  --systems direct_llm search_agent evidence_agent full_stack \
  --config configs/benchmark.yaml \
  --concurrency 2 \
  --orchestrator-concurrency 1 \
  --qwen-concurrency 2 \
  --qwen-initial-concurrency 1 \
  --qwen-rpm 60 \
  --judge-concurrency 4 \
  --url-concurrency 10 \
  --output outputs/tech_benchmark_openalex_formal_current/results.jsonl \
  --summary outputs/tech_benchmark_openalex_formal_current/summary.json \
  --report outputs/tech_benchmark_openalex_formal_current/EVALUATION_REPORT.md \
  --comparison-dir outputs/tech_benchmark_openalex_formal_current/comparison
```

脚本按 `case_id + system + model + config_hash` 去重并断点续跑。本轮已完成；后续重复运行同一命令只会检查已有记录，不会重复调用已完成样本。

## 完成后的收口命令

```bash
PYTHONPATH=. .venv/bin/python scripts/run_tech_benchmark.py \
  --mode evaluate \
  --input outputs/tech_benchmark_openalex_formal_current/results.jsonl \
  --output outputs/tech_benchmark_openalex_formal_current/results.jsonl \
  --summary outputs/tech_benchmark_openalex_formal_current/summary.json \
  --report outputs/tech_benchmark_openalex_formal_current/EVALUATION_REPORT.md \
  --comparison-dir outputs/tech_benchmark_openalex_formal_current/comparison

PYTHONPATH=. .venv/bin/python scripts/replay_ablation.py \
  --input outputs/tech_benchmark_openalex_formal_current/results.jsonl \
  --output outputs/tech_benchmark_openalex_formal_current/replay_results.jsonl \
  --summary outputs/tech_benchmark_openalex_formal_current/replay_summary.json
```

## 结果解释边界

在 `summary.json` 生成并完成人工 Claim 抽检前，不提取简历提升数字。尤其要区分：

- `compression_ratio` 是当前压缩器的字符减少比例，不等于 API input-token 降幅；
- `content_quality_score` 不包含 latency/tool budget；
- `direct_llm` 的证据指标为 `null`，表示不适用；
- OpenAlex/arXiv fallback 结果不能表述成 Bocha 结果；
- 本轮使用 OpenAlex；不能把结果表述成 Bocha 搜索结果。
- `full_stack` 的 P95 为 396.17 秒，超过预注册的 360 秒目标；`oss_003/full_stack` 发生一次全局超时。
- 正式结果仍需人工抽检至少 20% Claim 后，才适合写成最终简历数字。

