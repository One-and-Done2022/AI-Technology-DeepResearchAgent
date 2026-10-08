# AI Technology DeepResearch Agent：完成审计

最后核对：2026-10-04

本文是项目交付前的事实清单。`已验证` 必须有代码、测试或运行输出；`部分验证` 不能直接写成简历结果；`未验证` 只能作为后续任务或预注册目标。

## 需求—证据矩阵

| 需求 | 当前状态 | 权威证据 | 说明 |
|---|---|---|---|
| DAG 分层并发与任务生命周期 | 已验证 | `src/orchestrator/orchestrator.py`、集成测试 | 需要面试展示状态转移和失败恢复日志 |
| 动态 replan 与三级降级 | 已验证 | `src/orchestrator/orchestrator.py`、超时测试 | 正式实验仍需统计恢复率 |
| Source–Claim–Evidence schema | 已验证 | `src/evidence/schemas.py`、`extractor.py`、`verifier.py` | 有四级核验状态和 EvidenceSpan |
| Claim 原子化 | 已验证 | `tests/test_overnight_benchmark.py` | 复合句会按从句切分 |
| IterResearch | 已验证 | `src/orchestrator/orchestrator.py`、research round 日志 | 已有轮数上限和停止原因 |
| Red-Blue 审计事件 | 已验证 | `src/adversarial/audit.py`、`src/adversarial/llm_loop.py`、`tests/test_quality_control.py`、`outputs/adversarial_llm_smoke/README.md` | 默认 benchmark 为确定性路径；LLM Red/Blue 已完成一次真实 API smoke，可通过配置显式启用 |
| `ADD / VERIFY / MODIFY / DELETE` 行为 | 已验证 | 审计单元测试与 `audit_events` | 缺少 Claim 时会产生 coverage/ADD 事件 |
| 事实/数字/引用/覆盖维度记录 | 已验证 | `red_issue_counts_by_dimension` | 默认记录计数；LLM 后端另有结构化维度分数原始输出 |
| L1/L2/L3 压缩 | 部分验证 | `src/compressor/context.py`、v5 校准 | L1/L2 是 dependency-light approximation |
| 共享证据记忆 | 部分验证 | `src/memory/evidence_memory.py`、memory 测试 | 需要正式运行证明跨任务复用收益 |
| ResearchBench 35 题 | 已验证 | `evaluation/benchmarks/research_bench.py` | 兼容入口已存在 |
| HotpotQA 适配器 | 已验证 | `evaluation/benchmarks/hotpotqa.py`、`tests/test_legacy_benchmarks.py` | mock EM/F1/pass@1/实体覆盖率通过；未与主实验混合 |
| TechResearchBench-Mini 30 题 | 已验证 | `evaluation/datasets/tech_research_mini.jsonl` | 5 类、每类 6 题 |
| 四系统统一后处理 | 已验证 | `scripts/run_tech_benchmark.py`、测试 | 主统计为 direct/search/evidence/full_stack |
| DeepSeek 五维 Judge | 部分验证 | `evaluation/judge.py`、预检 | Judge API 可用，但不能替代客观证据指标 |
| Bootstrap 95% CI / Cohen’s dz | 已验证 | `evaluation/metrics/stats.py`、测试 | `n<2` 自动标记 insufficient_n |
| 5 × 4 OpenAlex 校准生成 | 已验证 | `outputs/tech_benchmark_openalex_calibration_current/` | 20/20 记录完成；用于接口和回放校准 |
| 30 × 4 正式生成 | 已验证 | `outputs/tech_benchmark_openalex_formal_current/results.jsonl` | 120 条记录，119 条成功，1 条 `full_stack` 全局超时 |
| Citation Entailment 实际提升 | 部分验证 | `replay_summary.json`、`summary.json` | 固定轨迹 0→0.180；正式 evidence/search +6.8pp，CI 跨 0 |
| Unsupported Claim Rate 实际下降 | 未达成 | `summary.json` | evidence 0.877、search 0.890，改善约 1.3pp，未达到预注册目标 |
| 输入 token 降低 35% | 未验证 | `replay_summary.json` | 当前只有字符压缩代理值，不能冒充 API input-token |
| Evidence Retention ≥93% | 部分验证 | `replay_summary.json` | 固定轨迹代理值 0.952；尚未完成 tokenizer 级正式统计 |
| P95 ≤360 秒 | 部分达成 | `summary.json` | search/evidence 达标，full_stack 为 396.17s |

## 当前可写入简历的事实

- 62 个自动化测试通过。
- 使用 Mock Search 完成 1 题 × 4 系统工程 smoke，验证 summary、审计、压缩、记忆和断点记录链路；结果保存在 `outputs/tech_benchmark_mock_smoke_v1/`，不属于真实 benchmark。
- 四系统评测脚本、断点续跑、usage 和错误记录链路已实现。
- 单题四系统校准可以生成结构化报告、Claim、Source、Judge 和运行时指标。
- 已完成 5 题 × 4 系统 OpenAlex 校准，并通过固定轨迹回放分别检查 Evidence、Red-Blue、压缩和 Memory 的后处理影响。
- 已完成 30 题 × 4 系统正式冻结协议评测；结果、失败记录和配对统计均保存在 `outputs/tech_benchmark_openalex_formal_current/`。
- v5 校准验证了压缩和证据保留字段可记录，但没有证明质量提升。

## 当前不可写成结果的内容

```text
内容质量提升约 12%
Citation Entailment 提升约 12pp
Unsupported Claim Rate 降低约 10pp
输入 token 降低约 35%
```

这些数字仍然是预注册目标。只有完成真实四系统配对实验、人工抽检和置信区间分析后，才能替换为观测值。

## 下一轮验收顺序

1. 抽检至少 20% Claim，记录 Judge 与人工一致率。
2. 修复 OpenAlex 检索噪声、Claim 与 citation 绑定和 full_stack 超时，再跑同一数据集的第二个 repeat。
3. 为压缩器补充 tokenizer 级 input-token 统计，并在跨任务协议下测 Memory 去重/命中收益。
4. 配置官方模型价格后重新聚合平均成本。
5. 若下一轮 CI 不跨 0，再把观测结果写入简历；否则继续使用“观察到趋势”的措辞。
