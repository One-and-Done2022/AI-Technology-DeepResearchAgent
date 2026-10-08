# AI Technology DeepResearch Agent：项目完成与面试作战手册

版本：2026-10-03

本文将简历中的每一条描述映射到代码、实验和面试回答。原则是：能在代码、测试或结果文件中复现的内容才写成“已完成”；12%、12pp、35%、93% 和 360 秒是预注册目标，未完成冻结版本的真实实验前不能写成观测结果。

## 1. 项目一句话

这是一个面向 AI/ML、软件系统与开源生态的证据驱动研究 Agent：系统将复杂技术问题拆成 DAG 子任务，调用多源检索，生成原子 Claim，并将 Claim 绑定到 Source/Evidence，再通过核验、IterResearch、Red-Blue 审计和可回放评测生成可追溯报告。

面试开场可以说：

> 普通搜索 Agent 能找到资料，但很难回答“这句话由哪个来源支持、证据是否冲突、还缺什么信息”。我的核心改造不是继续堆 Agent 数量，而是把报告从一段文本变成可审计的 Claim–Evidence 图，并用统一 benchmark 分离搜索、证据核验、迭代研究和质量控制的边际贡献。

## 2. 简历描述与实现证据

| 简历内容 | 代码位置 | 必须展示的证据 |
|---|---|---|
| DAG、Semaphore、9 状态、replan、三级降级 | `src/orchestrator/orchestrator.py`、`src/orchestrator/schemas.py` | 状态转移日志、失败注入测试、`finalization_state`、超时/重规划字段 |
| Source–Claim–Evidence | `src/evidence/schemas.py`、`extractor.py`、`verifier.py` | 一条 Claim JSON、EvidenceSpan、四级核验状态 |
| IterResearch | `src/orchestrator/orchestrator.py`、`ResearchWorkspace` | round 数、follow-up query、停止原因、信息缺口 |
| Red-Blue 审计 | `src/adversarial/audit.py`、`llm_loop.py` | `ADD/MODIFY/VERIFY/DELETE`、维度计数、接受率、震荡次数 |
| L1/L2/L3 压缩 | `src/compressor/context.py` | 原始/压缩 token、compression ratio、evidence retention |
| 共享记忆 | `src/memory/evidence_memory.py`、`src/evidence/store.py` | 去重数、memory size、检索命中、SQLite round-trip |
| 四系统消融 | `scripts/run_tech_benchmark.py` | `direct_llm/search_agent/evidence_agent/full_stack` 的统一后处理与配对比较 |
| 评测统计 | `evaluation/metrics/claim_metrics.py`、`stats.py`、`evaluation/judge.py` | 客观指标、DeepSeek 五维 Judge、Bootstrap CI、Cohen's dz |

当前已将 `FINALIZING` 作为真实第九个编排状态接入：它在报告进入 `DONE` 前统一写入终止原因、证据适用性和交付指标。不是为了增加一个空枚举，而是为了把“合成完成”和“可交付报告”分开。

## 3. 现在已经完成和没有完成的事情

### 已验证

- `.venv/bin/python -m pytest -q`：`70 passed`。
- `compileall` 和 `git diff --check` 通过。
- Qwen/Qwen2.5-7B-Instruct API 预检通过，并返回真实 usage。
- DeepSeek-V4-Flash API 预检通过，并能返回结构化 Judge 结果。
- 四系统脚本、Claim 抽取、Evidence Store、断点续跑、usage/cost 字段和统计函数可运行。
- 本地 mock smoke 可生成四份报告和系统级 summary。

### 当前正式评测结果

- 当前冻结版本使用 OpenAlex，完成 30 题 × 4 系统、120 条记录；119 条生成成功，1 条 `full_stack` 因全局超时失败。
- `direct_llm / search_agent / evidence_agent / full_stack` 的 Judge 内容均值为 6.01 / 2.95 / 2.67 / 3.19；规则内容均值为 8.31 / 8.46 / 8.31 / 8.23。
- `evidence_agent` 相比 `search_agent` 的 Citation Correctness 为 0.258 vs 0.190，观察到 +6.8pp，但 Bootstrap 95% CI 跨 0；Unsupported Claim Rate 仅改善约 1.3pp。
- `full_stack` P95 为 396.17s，超过 360s 目标；固定轨迹压缩回放的字符压缩率为 34.3%，Evidence Retention 代理值为 95.2%，不能直接写成 input-token 降幅。
- 内容提升约 12%、Citation Entailment 提升约 12pp、Unsupported Claim Rate 降低约 10pp、token 降低约 35%，仍是预注册目标，不是当前结果。

## 4. 完成项目的执行顺序

### Gate 0：冻结协议

固定模型 ID、temperature、max tokens、搜索后端、`as_of` 日期、数据集 hash、Git commit、并发参数和价格表。运行记录必须包含：

```text
case_id + system + model + config_hash
dataset_hash / git_commit / timestamp
error_type / elapsed / input_tokens / output_tokens
tool_calls / sources / claims / judge usage / cost
```

### Gate 1：搜索服务恢复

运行：

```bash
PYTHONPATH=. .venv/bin/python scripts/preflight_overnight.py
```

只有 `qwen.ok == true`、`judge.ok == true`、`search.ok == true` 才进入主实验。不能用 Mock Search 生成简历质量数字。

### Gate 2：5 题开发校准

运行 5 题 × 4 系统，检查：

- `direct_llm`：工具调用 0、sources 为空、证据指标为 `null`；
- `search_agent`：有 sources/claims，但不做生成阶段核验；
- `evidence_agent`：固定一轮核验；
- `full_stack`：可触发第二轮、Red-Blue、压缩、memory，并保存 runtime metrics；
- Claim Judge JSON 解析成功率 ≥98%；
- citation entailment 不恒为 0，unsupported rate 不因解析失败恒为 1；
- 每条记录能按 record key 恢复且没有重复。

任何一项失败都先修链路，不启动 30 题主实验。

### Gate 3：正式配对实验

```text
30 questions × 4 systems × 1 repeat = 120 runs
```

所有系统使用同一个 Qwen、相同题目、相同输出预算；后处理统一 Claim 抽取。主比较为：

| 比较 | 解释 |
|---|---|
| `search_agent - direct_llm` | 检索和 DAG 的增量价值 |
| `evidence_agent - search_agent` | Claim–Evidence 核验的增量价值 |
| `full_stack - evidence_agent` | IterResearch + Red-Blue + 压缩 + memory 的增量价值 |
| `full_stack - direct_llm` | 完整系统的总体收益与成本 |

### Gate 4：模块级消融

固定同一份初始搜索轨迹，再比较：

```text
full_stack
full_stack_without_redblue
full_stack_without_compressor
full_stack_without_memory
```

否则搜索结果变化会和模块收益混淆。Red-Blue 重点看 unsupported/contradicted、修复接受率和人工一致率；压缩重点看 token reduction 与 evidence retention 的联合曲线；memory 重点看重复来源率、检索命中和跨任务复用收益。

### Gate 5：统计与人工复核

对同题差值报告均值、中位数、标准差、配对 Bootstrap 95% CI 和 Cohen's dz。至少抽检 20% Claim，记录 Judge 与人工的 supported/partial/contradicted/unknown 一致率；若 CI 跨 0，只能写“观察到提升趋势”。

## 5. 指标口径

### 内容质量

- `topic_coverage`：命中 expected topics / expected topics 总数；
- `reference_claim_recall`：命中参考 Claim / 已标注参考 Claim；
- `abstention_accuracy`：可回答题回答、不可回答题拒答的正确率；
- DeepSeek 五维分：`factual_accuracy`、`comprehensiveness`、`analysis_quality`、`presentation`、`instruction_following` 的 0–10 平均；
- `system_success`、P50/P95 latency、input/output tokens、tool calls、单题成本。

### 证据质量

```text
Citation Entailment = (supported + 0.5 × partially_supported) / cited_claims
Unsupported Claim Rate = (unknown + contradicted) / verifiable_claims
Evidence Retention = retained_important_evidence / original_important_evidence
Token Reduction = 1 - compressed_tokens / original_tokens
```

`direct_llm` 没有来源，citation 类指标为 `null` 而不是 0；`null` 是不适用，0 是适用但没有命中。

## 6. 面试五分钟演示顺序

1. 先讲问题：报告有来源列表，但结论无法逐句追溯。
2. 展示一条 `Claim → EvidenceSpan → Source` JSON。
3. 展示四系统能力矩阵，说明每次只增加一层能力。
4. 展示一次 IterResearch：缺口识别 → 定向补搜 → 核验 → 停止。
5. 展示一条 Red-Blue 事件和一条压缩指标：问题、动作、是否接受、证据保留率。
6. 展示 summary 中的客观指标、Judge 分、CI、延迟和成本。
7. 主动讲一个失败案例：搜索噪声或证据绑定退化，以及下一步修复。

## 7. 高频面试问答

### 为什么不从零重写？

原骨架的 DAG、并发、模型路由和失败恢复已经可用。我保留底层基础设施，把主要工作放在 AI 技术情报场景、结论级证据链和可复现评测上；这样每个新增模块都能通过消融实验验证。

### 为什么 direct 可能比 full_stack 高？

7B 模型对短回答可能更稳定，而 Agent 会引入低质量检索、引用绑定错误、上下文膨胀和多轮合成退化。这个结果说明瓶颈在检索和证据整合，不等于工程没有价值；需要分别查看内容、证据和效率指标。

### 为什么 direct 的证据指标是 N/A？

它没有外部 Source，因此没有 citation entailment 的分母。强行记 0 会把“不适用”误报成“能力失败”。

### Red-Blue 和 DeepSeek Judge 的区别？

Red-Blue 是生成链路内部的主动审计和修复；DeepSeek Judge 是链路外的统一评测器。Judge 不接收 system 名称和内部状态，避免系统给自己打分。

### 如何证明压缩有效？

不能只看 token 减少。必须同时报告 `Token Reduction` 和 `Evidence Retention`；如果省了 token 但删掉关键证据，压缩就是失败。

### 如何证明 IterResearch 有用？

比较 `evidence_agent` 与 `full_stack`，记录二轮触发率、新增有效来源、缺口关闭率、reference claim recall 和完整性分。如果二轮只增加噪声，就要调整缺口识别和来源排序。

### 85%→95% 是什么？

只能指结构化 JSON 响应解析成功率，不能指事实准确率或报告质量。当前只有一次 LLM Red-Blue smoke，尚不能把该数字写成统计结果。

### 如果最终指标不提升怎么办？

如实报告，并定位是召回、来源质量、Claim 绑定、压缩、核验过度删除还是模型尺寸问题。一个能解释失败、保留回放记录并设计下一轮实验的系统，比只给出一个不可复现的正向数字更可信。

## 8. 简历数字的最终填法

当前冻结版本已完成 Gate 3，Gate 5 还差人工 Claim 抽检和成本单价配置；简历先使用下面的“观察到趋势”版本：

> 在 TechResearchBench-Mini 30 题四系统配对评测中完成 120 条可回放记录（119 条生成成功）；Evidence 相较普通搜索 Agent 的 Citation Correctness 观察到 +6.8pp 趋势，Unsupported Claim Rate 改善约 1.3pp，但 CI 跨 0；固定轨迹压缩回放字符数减少 34.3%、Evidence Retention 代理值 95.2%，full_stack P95 为 396.17s。

若面试官追问“为什么不是正向提升”，应写：

> 7B 模型下搜索噪声和多轮合成会抵消证据链收益；本轮结果证明了指标和消融链路可运行，也定位出下一轮要修复的是来源排序、Claim 绑定和 full_stack 超时，而不是继续堆 Agent 数量。

