# 固定轨迹模块回放结果

## 协议

本回放使用同一批 `search_agent` 生成的报告、来源和初始 Claim，不重新调用 Qwen、DeepSeek 或搜索服务。入口：

```bash
PYTHONPATH=. .venv/bin/python scripts/replay_ablation.py \
  --input outputs/tech_benchmark_openalex_calibration_current/results.jsonl \
  --output outputs/tech_benchmark_openalex_calibration_current/replay_results.jsonl \
  --summary outputs/tech_benchmark_openalex_calibration_current/replay_summary.json
```

输出：[replay_summary.json](/home/liuchenyang/deepresearch-agent/outputs/tech_benchmark_openalex_calibration_current/replay_summary.json)

回放系统：

```text
search_replay       原始 Claim/引用绑定，不做内部 Evidence 核验
evidence_replay     在同一报告上执行 Evidence 核验
redblue_replay      Evidence + Red-Blue
compressor_replay   Evidence + 上下文压缩
memory_replay       Evidence + Memory 写入/去重
full_replay         Evidence + Red-Blue + 压缩 + Memory
```

## 5 题回放结果

| 系统 | Rule Content | Citation Entailment | Unsupported Claim Rate | Topic Coverage | Compression Ratio | Evidence Retention |
|---|---:|---:|---:|---:|---:|---:|
| `search_replay` | 6.690 | 0.000 | 1.000 | 0.740 | N/A | N/A |
| `evidence_replay` | 6.690 | 0.210 | 0.937 | 0.740 | N/A | N/A |
| `redblue_replay` | 6.690 | 0.210 | 0.937 | 0.740 | N/A | N/A |
| `compressor_replay` | 6.550 | 0.210 | 0.937 | 0.700 | 0.338 | 0.900 |
| `memory_replay` | 6.690 | 0.210 | 0.937 | 0.740 | N/A | N/A |
| `full_replay` | 6.550 | 0.210 | 0.937 | 0.700 | 0.338 | 0.900 |

## 解释

- Evidence 核验在固定报告上把 Citation Entailment 从 `0` 提升到 `0.210`，并把 Unsupported Claim Rate 从 `1.000` 降到 `0.937`。这是核验状态重算的后处理效果，不是重新生成报告后的整体质量提升。
- Red-Blue 在这一批固定报告上没有改变这些客观指标，说明当前确定性审计策略尚未产生可观测边际收益；不能在简历中写成已经证明有效。
- 压缩使文本字符数减少约 `33.8%`，但 Topic Coverage 从 `0.740` 降到 `0.700`，代理 Evidence Retention 为 `0.900`。这提示当前压缩预算偏激进，需要提高证据保留约束后再做正式实验。
- Memory 在单个报告的离线回放中不改变正文，因此不能用这一回放证明跨任务复用收益。Memory 必须在多任务、共享工作区协议下单独测量去重和检索命中。

## 面试口径

> 为了避免把模型随机性误归因给模块，我把同一份搜索报告固定下来，只重跑 Evidence、Red-Blue、压缩和 Memory。结果显示 Evidence 的引用状态能被客观改善，但 Red-Blue 目前没有独立收益，压缩存在覆盖损失，Memory 需要跨任务实验才能证明价值。因此我把模块效果拆开报告，而不是只展示 full_stack 与 direct 的一个总分。

这份回放不替代真实生成 benchmark，也不支持把 `0.210`、`0.937` 或 `33.8%` 直接写成正式简历提升数字。

