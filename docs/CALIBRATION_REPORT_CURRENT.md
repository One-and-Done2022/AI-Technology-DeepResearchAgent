# TechResearchBench-Mini 当前校准报告

## 运行标识

- 数据集：`evaluation/datasets/tech_research_mini.jsonl`
- 规模：5 题 × 4 系统 = 20 条有效记录
- 系统：`direct_llm`、`search_agent`、`evidence_agent`、`full_stack`
- 生成模型：`Qwen/Qwen2.5-7B-Instruct`
- 外部 Judge：`deepseek-ai/DeepSeek-V4-Flash`
- 搜索后端：`OpenAlex`（不是 Bocha；Bocha 预检时返回配额不足）
- 结果文件：[results.jsonl](/home/liuchenyang/deepresearch-agent/outputs/tech_benchmark_openalex_calibration_current/results.jsonl)
- 汇总文件：[summary.json](/home/liuchenyang/deepresearch-agent/outputs/tech_benchmark_openalex_calibration_current/summary.json)
- 报告对照包：[comparison](/home/liuchenyang/deepresearch-agent/outputs/tech_benchmark_openalex_calibration_current/comparison)

## 系统级结果

| 系统 | 成功率 | Judge 内容分 | 规则内容分 | Topic Coverage | Reference Claim Recall | Citation Coverage | Citation Entailment | Unsupported Claim Rate | P95 延迟 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `direct_llm` | 100% | 6.24 | 6.51 | 0.770 | 0.200 | N/A | N/A | N/A | 17.37s |
| `search_agent` | 100% | 3.84 | 7.10 | 0.740 | 0.400 | 0.376 | 0.178 | 0.876 | 211.77s |
| `evidence_agent` | 100% | 3.76 | 6.50 | 0.770 | 0.200 | 0.348 | 0.249 | 0.833 | 224.10s |
| `full_stack` | 100% | 3.52 | 6.51 | 0.780 | 0.200 | 0.390 | 0.398 | 0.770 | 298.66s |

运行时指标：`full_stack` 的平均 `compression_ratio` 为 `0.3519`，表示压缩器输入文本的字符数减少约 35.2%；它不是 API 真实 input-token 降幅。`Evidence Retention` 为 `0.986`，是当前压缩器基于 Claim 词项保留的代理指标，不是人工逐条证据核验结果。所有有来源系统的 URL reachability 均为 `1.0`。本轮没有配置价格表，因此成本字段为 `N/A`，不能估算为真实金额。

`reference_claim_recall` 使用 sentence-level best-match：每个参考 Claim 与报告中最佳匹配句子的 `evidence_overlap` 达到 `0.55` 才计为命中。它是可复现的规则代理，不等同于人工事实核查。

## 配对观察

| 比较 | 指标 | 均值差值（右侧 − 左侧） | Bootstrap 95% CI | Cohen's dz | 当前解释 |
|---|---|---:|---:|---:|---|
| `search_agent - direct_llm` | Judge 内容分 | -2.40 | [-4.36, -0.32] | -0.926 | 搜索链路当前引入噪声，不能说明搜索在所有任务上无效 |
| `evidence_agent - search_agent` | Citation Entailment | +0.0715 | [-0.1754, 0.2775] | 0.239 | 方向偏正，但样本小且未固定公共搜索轨迹 |
| `evidence_agent - search_agent` | Unsupported Claim Rate | -0.0437 | [-0.1320, 0.0365] | -0.401 | 有下降趋势，但 CI 跨 0 |
| `full_stack - evidence_agent` | Citation Entailment | +0.1485 | [0.0037, 0.3352] | 0.691 | 校准中观察到证据质量改善，必须在正式集复核 |
| `full_stack - evidence_agent` | Unsupported Claim Rate | -0.0632 | [-0.1208, -0.0087] | -0.874 | 校准中观察到下降，仍不能替代正式结果 |
| `full_stack - direct_llm` | Judge 内容分 | -2.72 | [-4.80, -0.64] | -0.965 | full_stack 当前内容生成退化，需要继续修复检索、核验和审计链路 |

## 结果边界

这不是最终 30 题 benchmark，原因有三点：

1. `n=5`，只能用于开发校准和定位问题；
2. 四个系统仍然独立生成，搜索轨迹和初始报告没有完全固定，模块收益存在生成随机性混杂；
3. 本轮实际使用 OpenAlex，不能把结果表述为 Bocha 评测。

因此当前不能把以下预注册数字写成已达成结果：

```text
内容质量 +12%
Citation Entailment +12pp
Unsupported Claim Rate -10pp
输入 token -35%
Evidence Retention >=93%
P95 <=360s
```

其中字符减少 `35.2%` 和代理 Evidence Retention `98.6%` 是本轮 `full_stack` 的校准观察值，不是 API token 和人工证据保留的正式结论；P95 `298.66s` 也只覆盖 5 道题。

## 可供面试展示的结论

可以这样描述：

> 我先用 5×4 校准检查评测闭环。结果显示 full_stack 的 Citation Entailment 比 evidence_agent 高约 14.9 个百分点、Unsupported Claim Rate 低约 6.3 个百分点，但 Judge 内容分仍低于 direct_llm。这说明证据链对引用质量有帮助，但当前搜索噪声和多轮合成会损伤内容质量，所以后续需要固定搜索轨迹做公平回放，并优化 Claim–Citation 绑定和 Red-Blue 的保守修复策略。

不要这样描述：

> 我的完整系统整体质量提升了 12%。

当前校准并不能支持这句话。

## 下一步门槛

正式 30×4 实验前必须完成：

1. 公共搜索轨迹/初始报告的回放协议；
2. `full_stack` Red-Blue 的过度审计检查；
3. 5×4 校准结果人工抽检至少 20% Claim；
4. Bocha 或明确记录的 OpenAlex/arXiv fallback 预算与后端；
5. 成本价格表配置；
6. 重新运行完整 30 题配对实验。

