# AI Technology DeepResearch Agent：项目执行与面试手册

版本：2026-10-03

本文把简历中的每一条描述映射到代码、实验和面试回答。原则是：只有能在代码、日志或结果表中复现的内容，才能写成“已完成”；目标值必须标记为预注册目标。

## 1. 一句话项目定义

这是一个面向 AI/ML、软件系统与开源生态的证据驱动研究 Agent：它把自然语言问题拆成研究任务，调用多源检索工具收集材料，将报告拆成原子 Claim，并把每个 Claim 绑定到 Source/Evidence，经过核验、迭代补搜和审计后生成可回放的技术研究报告。

面试时先讲“解决什么问题”，再讲模块：

> 普通搜索 Agent 能找到资料，但不能稳定回答“这句话由哪个来源支持、证据是否冲突、还缺什么信息”。我的改造重点是把报告从一段文本变成可审计的 Claim–Evidence 图，并用统一 benchmark 分离搜索、核验、迭代研究和质量控制各自的贡献。

## 2. 简历条目与实现证据

| 简历描述 | 代码/日志证据 | 验证方式 |
|---|---|---|
| asyncio + Semaphore DAG 并发 | `src/orchestrator/orchestrator.py`、`src/core/runner.py` | 集成测试、运行时 `tool_calls`/`wall_seconds` |
| 9 状态生命周期、replan、三级降级 | `src/orchestrator/schemas.py`、`src/orchestrator/orchestrator.py` | 失败注入测试、日志中的状态转移；`FINALIZING` 负责交付前的指标与证据适用性收口 |
| Source–Claim–Evidence | `src/evidence/schemas.py`、`extractor.py`、`verifier.py` | Claim JSON、证据片段、核验状态 |
| IterResearch | `research` 配置、follow-up round | 轮次、停止原因、补搜 query |
| Red–Blue 审计 | `src/adversarial/audit.py` | `VERIFY / MODIFY / DELETE / ADD` 事件、事实/数字/引用/覆盖维度计数、修复接受率、震荡次数 |
| L1/L2/L3 压缩 | `src/compressor/context.py` | compression ratio、evidence retention |
| SQLite + NumPy 共享记忆 | `src/memory/evidence_memory.py` | 去重数、检索命中、memory size |
| 四级系统对照 | `scripts/run_tech_benchmark.py` | `direct_llm/search_agent/evidence_agent/full_stack`；`full_stack` 内部包含 IterResearch |
| 规则 + Judge + Bootstrap | `evaluation/` | `summary.json`、配对 CI、Cohen's dz |

### 实现口径校验（面试必须说清）

当前代码为了保持可部署性，部分模块是“可测量的轻量近似”，不是宣称已经接入大型专用模型：

- 压缩器的 L1 是哈希向量的 embedding-style 粗筛，L2 是基于词项重叠的 TextRank approximation，L3 才是显式证据保留；面试时说“轻量近似实现”，不要说成调用了某个未配置的 embedding 服务。
- 默认 benchmark 使用确定性的 `RedBlueAuditor`，按照 `unknown / contradicted / no citation` 触发 `VERIFY / MODIFY / DELETE`；另外提供可选的 `LLMRedBlueAuditor`，打开 `quality_control.adversarial_backend=llm` 后由 Red/Blue 分别进行 JSON 攻击与修复，并记录三层 JSON fallback 的解析策略和成功率。外部 DeepSeek Judge 仍负责独立评测。
- 共享记忆当前是进程内的 NumPy 证据索引和去重检索；若要声称跨任务持久化，必须以实际 SQLite 运行日志为证据。

这不是项目缺陷，而是工程取舍：正式 benchmark 默认使用稳定、可回放的确定性路径；需要展示 LLM Red/Blue 时再显式切换后端，并单独记录 API 成本和解析成功率。压缩器和记忆仍是 dependency-light approximation，并保留替换接口。

## 3. 项目完成顺序

### 阶段 A：冻结实验协议

固定以下变量：Qwen 模型 ID、Judge 模型 ID、temperature、最大输出 token、数据集 hash、as-of 日期、搜索后端、并发配置和 Git commit。每条记录必须包含 `record_key`、`config_hash`、`dataset_hash`、`git_commit`、usage、错误类型和延迟。

正式外部 API 评测使用 [configs/benchmark.yaml](/home/liuchenyang/deepresearch-agent/configs/benchmark.yaml)，不要直接复用本地 smoke 配置。该配置将 planner/solver/summarizer 的输出预算和研究轮次固定下来，降低因限流导致的不可比较波动。

主比较使用相同题目配对；旧的 `full_iterresearch` 仅作为历史配置兼容，不进入当前四系统主统计：

```text
A direct_llm       无检索、无生成阶段核验
B search_agent     有检索和 Claim/Source，不做核验
C evidence_agent   B + Claim–Evidence 核验，固定一轮
D full_stack       C + IterResearch + Red–Blue、上下文压缩、共享记忆
```

`direct_llm` 的证据指标必须是 `null`，表示不适用；不能用 0 冒充失败。

### 阶段 B：开发校准

先跑 2–5 道题，检查：

- direct 的工具调用为 0、来源为空；
- search 有来源但不执行生成阶段 Evidence 核验；
- evidence 固定一轮；
- full_stack 只在缺口条件满足时触发 IterResearch 第二轮；
- full_stack 有审计、压缩和 memory runtime metrics；
- Judge JSON 可解析、失败可重试、usage 可记录；
- 同一主键重复运行不会产生重复记录。

校准不通过就停止主实验，不生成效果提升数字。

### 阶段 C：正式实验（已完成）

正式实验为 TechResearchBench-Mini 30 题 × 4 系统，当前已完成 120 条记录，写入：

```text
outputs/tech_benchmark_openalex_formal_current/results.jsonl
outputs/tech_benchmark_openalex_formal_current/summary.json
outputs/tech_benchmark_openalex_formal_current/EVALUATION_REPORT.md
outputs/tech_benchmark_openalex_formal_current/comparison/
```

本轮 119/120 条生成成功，1 条 `full_stack` 因全局超时失败；四系统每题成对、主键无重复、Judge 无错误。结果显示 `direct_llm` 的 Judge 内容分最高，`evidence_agent` 相比 `search_agent` 的 Citation Correctness 观察到 +6.8pp 趋势但 CI 跨 0，`full_stack` P95 为 396.17 秒。不同 `dataset_hash`、`config_hash` 或搜索后端的结果不能合并。

### 阶段 D：统计与简历

对每个配对比较报告均值、中位数、标准差、配对 Bootstrap 95% CI 和 Cohen's dz。CI 跨 0 时只能写“观察到提升趋势”；只有 CI 不跨 0 且实验协议满足预注册要求时，才能写“显著提升”。

单题或单配对校准即使 Bootstrap 区间退化为一个点，也只允许做描述性比较；统计汇总会标记 `insufficient_n=true`，不会将其渲染为“显著提升/下降”。

预注册目标（尚不是结果）：

```text
内容质量 +12%
Citation Entailment +12pp
Unsupported Claim Rate -10pp
输入 token -35%
Evidence Retention >=93%
P95 latency <=360s
```

## 4. 指标如何解释

### 内容质量

- `topic_coverage`：报告覆盖题目期望主题的比例。
- `reference_claim_recall`：报告命中基准原子 Claim 的比例。
- `content_score`：规则指标与 DeepSeek 五维 Judge 分开报告；不把 Citation 指标混入内容分。
- Judge 五维：事实准确性、完整性、分析质量、表达、指令遵循。

### 证据质量

- `citation_coverage`：可验证 Claim 中带有效引用的比例。
- `citation_entailment`：`(supported + 0.5 × partially_supported) / cited_claims`。
- `unsupported_claim_rate`：`(unknown + contradicted) / verifiable_claims`。
- `contradicted_claim_rate`：被来源明确反驳的 Claim 比例。
- `primary_source_rate`：官方文档、论文原文、仓库等一手来源比例。
- `url_reachability`：来源 URL 可访问比例。

### 系统效率

- `P50/P95 latency`：从单题开始到记录落盘的墙钟时间。
- `input/output tokens`：优先使用 API response usage；拿不到时必须标记 estimated。
- `tool_calls`：搜索、读取、GitHub 等工具调用次数。
- `evidence_retention`：压缩后保留的重要证据 Claim 数 / 压缩前重要证据 Claim 数。

## 5. 高频面试问题与标准回答

### Q1：为什么不直接从零重写？

原项目已经有可靠的异步 DAG、模型路由和失败恢复，我保留这些底层能力，把工作集中在领域化和可验证性：新增技术研究对象、Claim–Evidence、来源质量、定向补搜和可回放 benchmark。这样改动能被消融实验验证，而不是只增加代码量。

### Q2：五个系统的差别是什么？

差别只在生成阶段能力配置，后处理 Claim 抽取统一。这样可以分别估计检索、证据核验、IterResearch 和质量控制的边际贡献，避免某个系统因为输出格式不同而获得评测优势。

### Q3：为什么 `direct_llm` 可能比 Agent 高？

7B 模型对短问题的直接回答可能更稳定；Agent 会引入低质量搜索结果、上下文膨胀、引用绑定错误和多轮合成退化。因此 direct 更高并不说明 Agent 无价值，而是暴露了检索召回和证据整合仍是瓶颈。需要看 Topic Coverage、Citation Entailment、Unsupported Claim Rate 和成本，而不是只看一个 Judge 总分。

### Q4：怎么证明 Evidence 模块真的有用？

在同一题目、同一模型和同一搜索轨迹上比较 `search_agent` 与 `evidence_agent`，主要看 Citation Entailment、Unsupported Claim Rate、Contradicted Claim Rate 和人工抽检一致率；内容质量只是辅助指标。

### Q5：怎么证明 IterResearch 有用？

比较 `evidence_agent` 与 `full_stack`，记录补搜触发率、第二轮新增来源数、信息缺口关闭率、Reference Claim Recall 和完整性分。若补搜没有增加有效证据，说明停止条件或缺口识别需要优化。

### Q6：压缩为什么不是简单截断？

L1 用相关性做粗筛，L2 用句子图排序，L3 强制保留带引用句和重要 Evidence Claim。验收必须同时看 Token Reduction 和 Evidence Retention；只省 token 但丢证据不能算成功。

### Q7：Red Agent 和 Judge 有什么区别？

Red Agent 是生成链路内的主动审计与修复，目标是减少报告中的问题；DeepSeek Judge 是链路外的统一评测器，不能读取系统名称或内部状态。两者分离可以避免系统用自己的判断给自己打分。

### Q8：为什么要统一 Claim 抽取？

如果 direct 没有 Claim、search 有 Claim，指标差异可能来自评测器而不是系统能力。统一后处理后，所有报告都能计算主题覆盖和 Claim 召回；只有有来源系统才计算证据指标。

### Q9：`85% → 95%` 代表什么？

只代表结构化 JSON 响应解析成功率，不能解释成事实准确率或报告质量提升。面试中必须明确口径；如果新版本无法复现，就删除该数字。

### Q10：为什么不直接做 RL？

当前瓶颈首先是搜索召回、来源质量、证据绑定、上下文管理和报告合成。先做可解释的模块消融，建立可靠 reward 和 offline benchmark，再考虑 Search-R1/DeepResearcher 风格的 RL，否则训练出的优化目标可能只是迎合不稳定 Judge。

### Q11：如果最终 full_stack 仍不如 direct，如何解释？

如实报告，并定位差异来自哪一层：搜索噪声、压缩丢失、验证过度删除、IterResearch 追加了低质量来源，还是模型尺寸不足。工程项目的价值还体现在失败可观测、模块可消融和能提出下一轮修复方案。

### Q12：你如何保证结果可信？

固定数据集和模型版本；配对比较；记录 config/data/git hash；结果 JSONL 断点续跑；Judge 不读取系统名；对 20% Claim 做人工抽检；报告 CI、效果量和失败类型；不把预注册目标冒充结果。

## 6. 面试演示顺序（5 分钟）

1. 用一句话讲问题和用户；
2. 展示一条 `Source–Claim–Evidence` JSON；
3. 展示四系统能力矩阵；
4. 展示一题的四份报告对比和 Evidence 状态；
5. 展示 `summary.json` 中的配对 CI、延迟和成本；
6. 解释一个失败案例以及下一步优化。

不要从代码文件列表开始，也不要先讲“我写了多少 Agent”。面试官更关心：为什么这样设计、如何证明有效、结果不好时如何定位。

## 7. 最终简历数字填写规则

只从正式 `summary.json` 和固定轨迹 `replay_summary.json` 读取数字。当前推荐句式：

> 在 TechResearchBench-Mini 30 题四系统配对评测中完成 120 条可回放记录（119 条生成成功）；Evidence 相较普通搜索 Agent 的 Citation Correctness 观察到 +6.8pp 趋势，Unsupported Claim Rate 改善约 1.3pp 但 CI 跨 0；固定轨迹压缩回放字符数减少 34.3%、Evidence Retention 代理值 95.2%，full_stack P95 为 396.17 秒。

若某项只在开发校准中测得，必须标注“开发校准”；若 CI 跨 0，使用“观察到提升趋势”。
