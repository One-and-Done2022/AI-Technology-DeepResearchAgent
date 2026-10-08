# TechResearchBench-Mini 评测说明与实验记录

最后核对日期：2026-10-04

本文档说明当前项目**实际实现**的评测协议、数据集来源、指标定义和已经落盘的实验结果。目标值、开发集结果和正式结果严格分开；没有人工标注或外部真值支持的指标，不表述为“事实准确率”。

## 1. 评测要回答的问题

当前评测不是简单比较哪份报告更长，而是通过逐级增加能力，分别回答三个问题：

| 比较 | 自变量 | 希望回答的问题 |
|---|---|---|
| `search_agent - direct_llm` | 增加规划、多 Agent 和外部检索 | 搜索是否提高技术信息召回和内容质量？ |
| `evidence_agent - search_agent` | 增加内部 Claim–Evidence 核验 | 核验是否提高引用正确性并减少无依据结论？ |
| `full_iterresearch - evidence_agent` | 增加信息缺口识别和定向补搜 | 第二轮研究是否提高完整度？ |
| `full_iterresearch - direct_llm` | 完整系统相对单轮模型 | 全部工程能力的总体收益和成本是什么？ |

四个系统使用同一个生成模型。所有输出再经过同一套 Claim 抽取、规则评分和外部 Judge，避免因输出 schema 不同而得到不公平分数。

| 系统 | 外部检索 | Claim 抽取 | 生成阶段内部核验 | IterResearch |
|---|---:|---:|---:|---:|
| `direct_llm` | 否 | 是，统一后处理 | 否 | 否 |
| `search_agent` | 是 | 是 | 否 | 否 |
| `evidence_agent` | 是 | 是 | 是 | 否，研究轮数固定为 1 |
| `full_iterresearch` | 是 | 是 | 是 | 是，最多 2 轮 |
| `full_stack` | 是 | 是 | 是 | 是，最多 2 轮；额外开启 Red-Blue、压缩和共享记忆 |

`direct_llm` 没有外部来源，因此来源和证据指标记为 `null`（N/A），而不是 0。0 表示“适用但表现为零”，`null` 表示“该能力在此系统中不适用”。

正式 30×4 结果使用 `full_stack` 作为最终系统名；它等价于 `full_iterresearch` 再加上 Red-Blue、上下文压缩和共享 Memory。`full_iterresearch` 是能力矩阵中的独立概念名，不应与本轮 `full_stack` 结果混淆。

## 2. 数据集来源与构造

### 2.1 数据集身份

当前主数据集是 [`evaluation/datasets/tech_research_mini.jsonl`](../evaluation/datasets/tech_research_mini.jsonl)，项目内名称为 **TechResearchBench-Mini**。

这是为本项目场景**自行设计的领域 pilot 集**，不是从 HotpotQA、ResearchBench、DeepResearch Bench 或其他公开 benchmark 复制、翻译或抽样得到的。题目围绕系统的目标使用场景人工构造：

- AI/ML 方法解释与比较；
- Agent 架构和研究范式；
- 推理与系统基础设施；
- 软件工程与开发者工具；
- 开源生态、许可证和项目尽调。

当前正式主实验仍使用 TechResearchBench-Mini。仓库已提供历史兼容入口 `evaluation/benchmarks/research_bench.py`（35 题、11 个领域）和 `evaluation/benchmarks/hotpotqa.py`（EM、F1、pass@1、Gold Entity Coverage），但它们尚未进入历史 120-run，不能与该实验结果混写。

### 2.2 数据分布

数据集共 30 题，`as_of` 统一为 `2026-08-30`：

| 维度 | 分布 |
|---|---|
| 类别 | `ai_ml / agents / systems / software_tools / open_source` 各 6 题 |
| 难度 | medium 15、hard 10、adversarial 5 |
| 可回答性 | 可回答 25、不可回答 5 |
| 主题标签 | 共 148 个；每题 4–6 个 |
| 参考 Claim | 6 题有标注，共 7 条 |
| Gold source pattern | 9 题有标注，共 16 条 URL pattern |

5 道 adversarial 题使用虚构或待核验对象，检查系统能否在缺乏公开证据时拒绝确认，而不是编造模型、硬件、benchmark、构建系统或 GitHub 项目。

### 2.3 单题 schema

```json
{
  "id": "aiml_001",
  "category": "ai_ml",
  "query": "...",
  "as_of": "2026-08-30",
  "expected_topics": ["自注意力|self-attention", "QKV|query key value"],
  "required_claims": ["标准全局自注意力相对于序列长度具有平方级计算或存储开销"],
  "gold_source_patterns": ["arxiv.org/abs/1706.03762"],
  "preferred_source_types": ["paper", "official_doc"],
  "answerable": true,
  "difficulty": "medium"
}
```

字段含义：

| 字段 | 用途 | 当前限制 |
|---|---|---|
| `expected_topics` | 计算主题覆盖率；`|` 表示可接受的词面变体 | 只检查文本出现，不判断论述是否正确 |
| `required_claims` | 计算参考 Claim 召回率 | 仅 6/30 题有标注，不是完整事实库 |
| `gold_source_patterns` | 计算前 10 个来源的 gold recall/precision | 仅 9/30 题有标注；pattern 是种子来源，不代表所有有效来源 |
| `preferred_source_types` | 描述该题优先来源类型 | 当前没有直接进入总分 |
| `answerable` | 计算整篇回答/拒答是否正确 | 拒答由正则规则识别，仍需人工抽检 |
| `difficulty` | 分层分析和选题 | 当前汇总报告尚未按难度单独展示 |

### 2.4 标注来源与可审计边界

`required_claims` 与 `gold_source_patterns` 是项目维护者为 pilot 人工写入的参考标注。已写入的种子来源主要是代表性论文、官方文档和官方仓库，例如 Transformer、LoRA/QLoRA、MoE、MTEB、FlashAttention、ReAct，以及 LangGraph/AutoGen/CrewAI 官方文档。

当前 16 条 source pattern 的完整清单如下。`arxiv.org` 这种宽泛 pattern 只能检查是否召回论文站点，区分力弱于精确论文 ID：

| Case | Gold source patterns |
|---|---|
| `aiml_001` | `arxiv.org/abs/1706.03762` |
| `aiml_002` | `arxiv.org/abs/2106.09685`、`arxiv.org/abs/2305.14314` |
| `aiml_003` | `arxiv.org/abs/1701.06538`、`arxiv.org/abs/2101.03961` |
| `aiml_004` | `arxiv.org/abs/2210.07316`、`huggingface.co/spaces/mteb/leaderboard` |
| `aiml_005` | `arxiv.org/abs/2205.14135`、`github.com/dao-ailab/flash-attention` |
| `agent_001` | `arxiv.org/abs/2210.03629`、`arxiv.org/abs/2305.04091` |
| `agent_002` | `docs.langchain.com/oss/python/langgraph`、`microsoft.github.io/autogen`、`docs.crewai.com` |
| `agent_003` | `arxiv.org` |
| `agent_004` | `arxiv.org` |

必须明确以下边界：

- 当前 JSONL 没有 `annotator`、`annotation_date`、标注依据摘录或双人复核字段，因而只能称为项目自建标注，不能称为专家标注或独立审计数据集；
- gold source 只覆盖 9 题，而且是 URL 子串匹配，因此 `Gold Source Recall@10` 只衡量是否检索到预设种子来源；
- 题目没有划分 train/dev/test，提示词和流程优化已查看这些题目，存在开发集过拟合风险；
- 尚未完成公开 benchmark 的外部有效性验证，也没有做训练数据污染检测。

### 2.5 运行时信息来源不是 benchmark 真值

Agent 在生成阶段可以访问下列公开或第三方信息渠道，它们是**检索数据源**，不是数据集标签：

| 渠道 | 当前用途 | 鉴权 |
|---|---|---|
| Bocha Web Search | 通用网页搜索和候选 URL 发现 | `BOCHA_API_KEY` |
| OpenAlex / arXiv | 论文元数据与论文检索 | OpenAlex 当前可匿名使用；arXiv 为公开接口 |
| GitHub REST API | 仓库 metadata、README、license、release | token 可选；匿名额度更低 |
| Browser | 读取候选网页正文 | 公开网页，无统一 API key |

Qwen2.5-7B 是报告生成模型，DeepSeek-V4-Flash 是外部评分模型；二者都不是 gold truth 来源。

## 3. 指标体系

指标分为内容、检索与来源、证据、效率与可靠性、外部 Judge 五组。所有比率均在 `[0,1]`，Judge 分数在 `[0,10]`。

### 3.1 内容与任务完成指标

#### Topic Coverage

```text
Topic Coverage = 命中的 expected_topics 数 / expected_topics 总数
```

每个 topic 可以用 `A|B` 提供多个词面变体，任一变体出现在报告中即命中。该指标可复现但只测覆盖，不测语义正确性。

#### Reference Claim Recall

```text
overlap = 参考 Claim token 与报告 token 的交集 / 参考 Claim token 数
Reference Claim Recall = best_sentence_overlap >= 0.55 的参考 Claim 数 / 参考 Claim 总数

其中 `best_sentence_overlap` 是参考 Claim 与报告中最佳匹配句子的 `evidence_overlap`；这是可复现的规则代理，不等同于人工事实核查。
```

token 包括英文/数字 token 和中文二元字符。没有参考 Claim 的题目按 1.0 处理，因此全量均值会被大量未标注题目抬高；正式分析应同时报告“仅有标注题”的结果。

#### Abstention Accuracy

```text
Abstention Accuracy = 1[可回答题作答，或不可回答题拒答]
```

整篇拒答通过“无法回答、无法确认、缺乏公开证据”等模式识别。局部写“某一项证据不足”不应等同于整篇拒答。它仍是规则代理指标，不是自然语言推理分类器。

#### System Success

```text
System Success = 1[报告非空且不包含 Research failed]
```

这是工程成功率，不代表回答正确。

#### Rule Content Score

单题规则内容分定义为：

```text
10 × (0.40 × Reference Claim Recall
    + 0.35 × Topic Coverage
    + 0.15 × Abstention Accuracy
    + 0.10 × System Success)
```

效率不再混入内容质量分，而是单独记录 `efficiency`。实现中保存 `judge_content_score`、`rule_content_score`、`content_quality_score` 和历史兼容字段 `content_score`；报告的“系统结果”同时展示 Judge Content 和 Rule Content，解释结果时必须注明分数来源，不能把二者混为一个总分。

### 3.2 检索与来源指标

#### Gold Source Recall@10

```text
Recall@10 = 被前 10 个 URL 命中的 gold URL pattern 数 / gold pattern 总数
```

#### Gold Source Precision@10

```text
Precision@10 = 前 10 个 URL 中命中任一 gold pattern 的 URL 数 / 前 10 个 URL 数
```

两项指标只在带 `gold_source_patterns` 的 9 道题上适用，其余为 `null`。

#### Source Quality

每个来源先按 URL/metadata 分类，再使用固定先验分：paper 1.00、official document 0.95、official repository 0.90、institutional 0.85、repository 0.75、tech media 0.65、blog 0.45、unknown 0.35；无 URL 减 0.20，摘录少于 40 字符减 0.10。报告分数是全部来源的平均值。

这是来源类型启发式，不是内容真实性评分。

#### Primary Source Rate

```text
Primary Source Rate = paper/official_doc/official_repository/institutional 来源数 / 来源总数
```

#### Source Diversity

```text
Source Diversity = min(1, 不同 host 数 / 3)
```

达到 3 个不同域名即满分，因此只适合检测极低多样性。

#### Source URL Syntax Validity 与 URL Reachability

```text
Syntax Validity = 以 http:// 或 https:// 开头的来源数 / 来源总数
URL Reachability = 实验时 HTTP GET 返回 status < 400 的 URL 数 / 检查 URL 总数
```

可访问不等于内容支持 Claim；反之，登录墙、限流或临时网络故障也可能让真实来源被记为不可访问。

### 3.3 Claim–Evidence 指标

Claim 类型限定为 `definition / mechanism / comparison / performance / cost / temporal / adoption / license / recommendation / negative`。`recommendation` 默认不作为可验证事实 Claim。

内部 verifier 使用词项重合和数值一致性输出：

```text
supported / partially_supported / contradicted / unknown
```

正式汇总优先使用 DeepSeek 对“原子 Claim + 引用摘录”的外部判定，避免直接使用系统内部核验给自己打分。

#### Citation Coverage / Citation Completeness

```text
Cited Claims / Verifiable Claims
```

当前两个字段公式相同，是兼容性重复指标，不能当成两项独立证据。

#### Citation Correctness

```text
(supported + 0.5 × partially_supported) / Cited Claims
```

这里的 supported 状态来自外部 Judge。无引用 Claim 不进入分母，但会进入 Unsupported Claim Rate。

#### Unsupported Claim Rate

```text
(unknown + contradicted + 未得到 Judge 结果的 Claim) / Verifiable Claims
```

越低越好。该实现将 `contradicted` 也归入 unsupported，因此需要结合 Contradicted Claim Rate 解读。

#### Unsupported Important Claim Rate

```text
高重要度 Claim 中 status 为 unknown 或 contradicted 的数量 / 高重要度 Claim 数
```

没有高重要度 Claim 时当前实现返回 0，这可能造成乐观偏差。

#### Contradicted Claim Rate

```text
contradicted / Verifiable Claims
```

#### 内部 Citation Entailment

规则 verifier 还计算：

```text
(supported + 0.5 × partially_supported) / Cited Claims
```

但其状态由 lexical overlap 阈值（支持 0.22、部分支持 0.08）和数值冲突规则产生。它适合离线回归检查，不应替代外部 Judge 或人工核验。

### 3.4 外部 DeepSeek 报告 Judge

DeepSeek-V4-Flash 在不知道系统内部评分的情况下，对每篇报告给出五个 0–10 分维度：

- `factual_accuracy`：报告陈述在给定问题下的事实合理性；
- `comprehensiveness`：问题要求的关键方面是否完整；
- `analysis_quality`：比较、权衡和推理是否充分；
- `presentation`：结构和可读性；
- `instruction_following`：是否遵循问题及输出要求。

```text
Judge Content Score = 五个维度的算术平均
```

Prompt 明确要求不因引用格式加分。证据正确性通过另一条 Claim Judge 流程单独计算。

局限：当前只有单一 Judge 模型、每题单次评分、没有位置交换或多 Judge 投票，也没有完成人工一致性校准，因此 Judge 分数只能作为模型代理评价。

### 3.5 效率、成本与工程可靠性

#### Efficiency

```text
latency_score = min(1, 180 / elapsed_seconds)，elapsed <= 0 时为 0
tool_score = min(1, 30 / max(tool_calls, 1))
Efficiency = (latency_score + tool_score) / 2
```

此外按系统报告 P50/P95 延迟、生成 input/output tokens、Judge tokens 和工具调用总数。

只有配置四项真实单价后才计算人民币成本：

```text
QWEN_INPUT_PRICE_PER_M
QWEN_OUTPUT_PRICE_PER_M
DEEPSEEK_INPUT_PRICE_PER_M
DEEPSEEK_OUTPUT_PRICE_PER_M
```

缺少任一单价时 `average_cost_cny=null`，禁止用估算值冒充真实成本。

工程记录还保存 `case_id + system + model + config_hash` 恢复键、模型 ID、Judge ID、Git commit、数据集 hash、UTC 时间、错误、并发参数和实际 usage。

## 4. 统计方法

每个系统对同一批题运行，比较时只使用两系统都完成的公共 `case_id`：

```text
d_i = score_right(i) - score_left(i)
```

当前统计输出包括：

- 均值、中位数、样本标准差和 P95；
- 配对 bootstrap 10,000 次的 percentile 95% CI；
- 双侧 bootstrap 尾概率；
- paired Cohen's dz：`mean(d) / sample_std(d)`。

当前配对结果同时覆盖 Judge Content、Rule Content、Topic Coverage、Reference Claim Recall、Abstention Accuracy，以及适用时的 Citation Correctness 和 Unsupported Claim Rate。客观指标的配对样本仍必须满足同一 `case_id` 且两系统均有该指标。

CI 全部大于 0 才写“显著提升”，全部小于 0 写“显著下降”；CI 跨 0 只能写“提升/下降趋势或无显著差异”。当前只有一次 30 题 pilot，不是重复性实验，也不支持强因果结论。当前 bootstrap 未固定随机种子，所以重复聚合时 CI 末位可能轻微变化。

## 5. 已完成的 120-run 正式冻结协议实验

### 5.1 实验身份

| 项目 | 记录 |
|---|---|
| 结果文件 | `outputs/tech_benchmark_openalex_formal_current/results.jsonl` |
| 汇总文件 | `outputs/tech_benchmark_openalex_formal_current/summary.json` |
| 可读报告 | `outputs/tech_benchmark_openalex_formal_current/EVALUATION_REPORT.md` |
| 运行量 | 30 题 × 4 系统 × 1 次 = 120 runs |
| 生成模型 | `Qwen/Qwen2.5-7B-Instruct` |
| Judge | `deepseek-ai/DeepSeek-V4-Flash` |
| 搜索后端 | `OpenAlex` |
| 生成成功 / Judge 错误 / 重复恢复键 | 119/120 / 0 / 0 |
| 当前数据集 hash | `42bcf36e14fa224399a94c86d50ecef0bdf6a780abc0d749629a1c773a6b3ae4` |

本轮结果使用当前数据集和 OpenAlex 搜索后端。如果后续修改题库、配置、模型或搜索后端，必须新建输出目录，不能与本轮记录混合。

### 5.2 核心结果

以下数字取自已落盘的 `summary.json`：

| 系统 | Runs | Judge Content | Rule Content | Topic Coverage | Ref Claim Recall | Abstention Acc. | P95 延迟 |
|---|---:|---:|---:|---:|---:|---:|---:|
| direct_llm | 30 | 6.013 | 8.305 | 0.787 | 0.800 | 0.900 | 26.838s |
| search_agent | 30 | 2.947 | 8.457 | 0.807 | 0.833 | 0.867 | 323.785s |
| evidence_agent | 30 | 2.673 | 8.310 | 0.803 | 0.800 | 0.867 | 336.320s |
| full_stack | 30 | 3.186 | 8.231 | 0.790 | 0.793 | 0.862 | 396.174s |

四个系统的 `System Success` 都是 1.000。Judge 五个原始维度如下，不能只保留总分而隐藏分项：

| 系统 | Factual Accuracy | Comprehensiveness | Analysis Quality | Presentation | Instruction Following |
|---|---:|---:|---:|---:|---:|
| direct_llm | 6.300 | 5.767 | 4.500 | 6.233 | 7.267 |
| search_agent | 3.067 | 2.833 | 2.567 | 3.033 | 3.133 |
| evidence_agent | 2.800 | 2.567 | 2.300 | 2.833 | 3.067 |
| full_stack | 3.367 | 3.300 | 2.733 | 3.467 | 3.100 |

| 有来源系统 | Citation Coverage | Citation Correctness | Unsupported | Contradicted |
|---|---:|---:|---:|---:|
| search_agent | 0.368 | 0.190 | 0.890 | 0.004 |
| evidence_agent | 0.382 | 0.258 | 0.877 | 0.004 |
| full_stack | 0.354 | 0.174 | 0.891 | 0.002 |

当前完整 pilot 的数据集快照早于 Gold Source 指标补标，因此不报告该次运行的 `Gold Source Recall@10/Precision@10`；若直接用当前标注重算，它属于 retrospective re-evaluation，而不是当时运行时冻结的结果。

生成资源总量：

| 系统 | Input tokens | Output tokens | Judge tokens |
|---|---:|---:|---:|
| direct_llm | 3,595 | 15,796 | 59,332 |
| search_agent | 3,595 | 15,796 | 197,048 |
| evidence_agent | 3,595 | 15,796 | 230,193 |
| full_stack | 3,595 | 15,796 | 261,346 |

成本字段为 N/A，因为结果记录中没有完整的模型单价配置。

### 5.3 配对结论

| 比较 | Mean diff | 95% CI | dz | 解释 |
|---|---:|---:|---:|---|
| search − direct：Judge Content | -3.067 | [-3.833, -2.253] | -1.349 | search 显著低于 direct |
| evidence − search：Judge Content | -0.273 | [-0.887, 0.353] | -0.156 | 无显著差异 |
| evidence − search：Citation Correctness | +0.077 | [-0.036, 0.202] | 0.227 | 观察到提升趋势，但 CI 跨 0 |
| evidence − search：Unsupported Claim Rate | -0.017 | [-0.075, 0.028] | -0.120 | 观察到下降趋势，但 CI 跨 0 |
| full − evidence：Judge Content | +0.483 | [-0.069, 1.048] | 0.308 | 观察到提升趋势，但 CI 跨 0 |
| full − direct：Judge Content | -2.814 | [-3.552, -2.062] | -1.349 | full 显著低于 direct |

结论必须如实表述：本轮正式冻结协议验证了 120 条记录的工程和评测闭环，但没有证明多 Agent 系统优于 direct。Evidence 核验在 Citation Correctness 上出现小幅改善趋势，IterResearch 的内容收益不稳定；引用绑定、低质量来源、长上下文合成和 7B 模型能力是当前主要问题。

## 6. 最新开发校验，不作为正式结果

`outputs/tech_benchmark_dev_v2/results.jsonl` 使用当前数据集 hash，截至 2026-09-17 已完成 20/20 条：direct、search、evidence、full 各 5 条，运行错误和 Judge 错误均为 0。它仍是看过主实验结果后反复修改实现的开发集，因此：

- 不与旧 120-run 合并；
- 不做不等题量的系统排名；
- 不用于简历中的效果提升数字；
- 只能用于定位 Citation 绑定、来源质量和拒答规则问题。

### 6.1 开发集客观结果

| 系统 | Judge Content | Rule Content | Topic Coverage | Ref Claim Recall | Abstention Accuracy | P95 延迟 |
|---|---:|---:|---:|---:|---:|---:|
| `direct_llm` | 5.68 | 6.980 | 0.810 | 0.300 | 1.000 | 36.13s |
| `search_agent` | 2.52 | 6.480 | 0.810 | 0.200 | 1.000 | 463.36s |
| `evidence_agent` | 2.40 | 5.641 | 0.630 | 0.200 | 0.800 | 651.06s |
| `full_iterresearch` | 3.32 | 6.147 | 0.730 | 0.200 | 1.000 | 576.07s |

| 有来源系统 | Gold Source R@10 | Primary Source Rate | Citation Coverage | Citation Correctness | Unsupported Claim Rate | 适用记录数 |
|---|---:|---:|---:|---:|---:|---:|
| `search_agent` | 0.200 | 1.000 | 0.092 | 0.583 | 0.939 | 2 |
| `evidence_agent` | 0.000 | 1.000 | 0.056 | 0.000 | 1.000 | 1 |
| `full_iterresearch` | 0.000 | 0.000 | 0.040 | 0.000 | 1.000 | 1 |

`Rule Content` 是代码根据参考 Claim、主题、拒答和系统成功率计算的客观/规则代理分；`efficiency` 单独报告；`Judge Content` 是 DeepSeek 五维均分。两者用途不同，不能互相替代。引用指标只对有来源且完成 Claim Judge 的记录聚合，当前 5 题校准只能用于调试方向，不能称为最终效果证据。

统计实现会对 `n < 2` 的配对比较标记 `insufficient_n=true`，即使 Bootstrap 区间退化为单点，也不会渲染为显著差异。

## 7. 当前评测完整性与下一步

### 7.0 OpenAlex 校准与固定轨迹回放

由于 Bocha 预检可能返回套餐额度不足，项目新增了无需 API Key 的 `openalex` 搜索后端，并在 OpenAlex 额度耗尽时自动降级到公开 arXiv Atom API。已完成固定 `configs/benchmark.yaml` 的 5 题 × 4 系统校准。该校准只用于验证接口、断点续跑和指标字段，不能作为正式 30 题简历效果数字。

校准输出：`outputs/tech_benchmark_openalex_calibration_current/`。本轮实际搜索后端为 OpenAlex；Bocha 预检因套餐额度不足未通过。完整结果和限制见 [`docs/CALIBRATION_REPORT_CURRENT.md`](CALIBRATION_REPORT_CURRENT.md)。

在相同 `search_agent` 报告和来源上，新增离线固定轨迹回放：

```text
search_replay → evidence_replay
evidence_replay → redblue_replay / compressor_replay / memory_replay / full_replay
```

入口为 `scripts/replay_ablation.py`，它不调用模型或搜索，只重跑后处理模块。该回放用于定位模块边际变化，不替代真实生成实验；当前结果显示 Evidence 改变了引用状态，压缩略微降低主题覆盖，Memory 在单个报告内没有内容变化，Red-Blue 尚未产生可观测的独立收益。

当前正式跑批：

```text
outputs/tech_benchmark_openalex_formal_v1/
30 题 × 4 系统 = 120 条目标记录
```

正式跑批采用 `direct_llm / search_agent / evidence_agent / full_stack`，与简历中的四级配对消融一致；历史 5 系统和 Bocha 结果不会混入本批。

| 评测层 | 当前状态 | 要成为可信 benchmark 仍缺什么 |
|---|---|---|
| 工程可靠性 | v3 校准 4/4 完成；正式 120 条仍在运行 | 在冻结版本上重复 3 次 |
| 内容覆盖 | 30 题均有 topic；仅 6 题有参考 Claim | 为 30 题补齐原子 Claim 真值并双人复核 |
| 检索 | 仅 9 题有 gold source | 扩充可接受来源池，记录来源版本和证据摘录 |
| 引用正确性 | 外部 DeepSeek Claim Judge | 人工抽检至少 20%，报告 Macro-F1 和 Cohen's kappa |
| 报告质量 | 单一 DeepSeek Judge、单次评分 | 多 Judge/重复评分、位置与长度偏差校准 |
| 消融公平性 | 主实验采用四系统；`full_iterresearch` 保留为可选内部对照 | 冻结同一 Search Trace 比较 search/evidence/full_stack，隔离检索随机性 |
| 统计 | 配对 bootstrap + dz | 固定随机种子；多指标校正；3 repeats |
| 外部有效性 | 仅自建领域集 | 增加公开 DeepResearch benchmark 或公开 QA/检索子集 |
| 成本 | usage 已记录 | 配置运行时官方单价并保存价格日期 |

建议下一版冻结为 `TechResearchBench-Mini v0.2`：补齐 30 题的原子 Claim、证据摘录和允许来源集合；将 10 题作为 dev、20 题作为不可见 test；在冻结 commit 上对四系统做重复实验，并先完成人工 Judge 校准，再写简历中的质量提升数字。

## 8. 复现入口

实现位置：

- 数据加载和单题评分：`evaluation/benchmarks/tech_research_bench.py`；
- 规则与 Claim 指标：`evaluation/metrics/claim_metrics.py`；
- DeepSeek 报告/Claim Judge：`evaluation/judge.py`；
- Bootstrap 和效应量：`evaluation/metrics/stats.py`；
- 四系统运行、断点续跑与汇总：`scripts/run_tech_benchmark.py`。

运行前检查生成、Judge 和搜索服务：

```bash
.venv/bin/python scripts/preflight_overnight.py
```

运行四系统对照实验：

```bash
.venv/bin/python scripts/run_tech_benchmark.py \
  --mode run \
  --limit 30 \
  --systems direct_llm search_agent evidence_agent full_stack \
  --config configs/benchmark.yaml \
  --concurrency 2 \
  --orchestrator-concurrency 1 \
  --qwen-concurrency 2 \
  --qwen-initial-concurrency 1 \
  --qwen-rpm 60 \
  --judge-concurrency 4
```

只聚合已有 JSONL：

```bash
.venv/bin/python scripts/run_tech_benchmark.py \
  --mode evaluate \
  --input outputs/tech_benchmark_openalex_formal_current/results.jsonl
```

重新评分会使用**当前代码和当前数据集标注**。如果 JSONL 的 `dataset_hash` 或 `git_commit` 与当前版本不一致，应输出到新的 summary 路径并标记为 retrospective re-evaluation，不能覆盖原实验报告。
