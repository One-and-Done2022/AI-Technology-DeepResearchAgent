# AI Technology Research Agent：STAR 与简历基准

版本日期：2026-10-04

本文件是项目实现、评测和简历编写的唯一基准。目标值不能作为已完成结果；只有真实 benchmark 输出才能填写到简历数字中。

## 项目定位

**AI Technology Research Agent：面向人工智能、软件系统与开源生态的证据驱动研究系统**

目标用户包括算法工程师、后端/基础设施工程师、技术架构师和技术产品经理。系统处理论文综述、技术路线比较、推理与 MLOps 选型、软件工具分析和 GitHub 项目尽调。

## STAR

### S — Situation

原始 DeepResearch Agent 已具有异步 DAG 编排、工具调用、记忆和报告合成，但通用任务边界过宽，最终报告只保留来源列表，无法把具体结论定位到原文证据；事实核验和评测主要依赖关键词/格式启发式，自进化训练仍是预留接口。

### T — Task

将通用多 Agent POC 改造成可验证的 AI 技术情报产品：

1. 支持论文、官方文档、GitHub 和网页多源研究；
2. 建立 Claim–Evidence 结论级证据链；
3. 使用有界 IterResearch 识别信息缺口并定向补搜；
4. 对引用、数值和来源冲突提供结构化验证状态；
5. 建立领域 benchmark，对比单轮 LLM、原始 Agent 和证据驱动版本；
6. 输出可回放日志、结构化报告和量化指标。

### A — Action

已经实现：

- 新增 `Source / Claim / EvidenceSpan / ResearchRound` 数据结构；
- 新增来源类型识别、质量评分、内容 hash 和 SQLite Evidence Store；
- Researcher 保存工具参数、来源、claims 和证据指标；
- Summarizer 使用统一 `[S#]` Evidence Catalog，禁止伪造来源编号；
- 新增保守的词项覆盖与数值一致性 verifier，输出 `supported / partial / contradicted / unknown`；
- 新增 GitHub Reader，读取 README、许可证、活跃时间和最新 Release；
- 新增有界 IterResearch workspace，对失败或来源不足任务创建定向核验轮次；
- 修复 DAG 不同执行层之间无法立即读取依赖结果的问题；
- 新增结构化 JSON 输出和运行时指标；
- 新增 30 道 `TechResearchBench-Mini`；
- 保留 `ResearchBench`（35 题、11 个领域）和 `HotpotQA` 的兼容评测入口；
- 新增 `direct_llm / search_agent / evidence_agent / full_stack` 四系统对比；`full_stack` 内部包含 IterResearch、Red-Blue、压缩和共享记忆；
- 新增带事实/数字/引用/覆盖维度计数的 Red-Blue 审计、证据保留压缩和 NumPy 共享记忆独立开关与指标；
- 增加 DeepSeek 外部报告/Claim Judge、真实 API usage、断点续跑与成本字段；
- 内容质量与证据质量分开统计，提供配对 Bootstrap 95% CI 与 Cohen's dz；
- 新增自动化单元和集成测试。

### R — Result

目前已经验证的结果：

| 项目 | 已验证结果 |
|---|---:|
| 领域评测题数 | 30 |
| 评测类别 | 5 |
| 每类题数 | 6 |
| 自动化测试 | 70 passed |
| Python 静态编译 | passed |
| Qwen2.5-7B / DeepSeek-V4-Flash API 预检 | passed |
| Evidence SQLite round-trip | passed |
| Researcher → Source → Summarizer → Claim 集成流 | passed |
| IterResearch follow-up/stop 条件 | passed |
| GitHub Reader 公开 API 实测 | metadata/README/license/release passed |
| 四系统评分、Judge、恢复与 Bootstrap 脚本 | 30 题 × 4 系统正式结果已落盘；119/120 条生成成功 |

正式 30×4 评测的真实结果：

| 系统 | Judge 内容分 | 规则内容分 | Topic Coverage | Citation Correctness | Unsupported Claim Rate | P95 延迟 |
|---|---:|---:|---:|---:|---:|---:|
| `direct_llm` | 6.01 | 8.31 | 0.787 | N/A | N/A | 26.84s |
| `search_agent` | 2.95 | 8.46 | 0.807 | 0.190 | 0.890 | 323.79s |
| `evidence_agent` | 2.67 | 8.31 | 0.803 | 0.258 | 0.877 | 336.32s |
| `full_stack` | 3.19 | 8.23 | 0.790 | 0.174 | 0.891 | 396.17s |

解释边界：`full_stack` 有 1 条全局超时记录，因此成功率为 29/30；`direct_llm` 的证据指标为 N/A，不是 0。当前搜索后端为 OpenAlex，成本因未配置官方价格变量而为 N/A。上述结果说明当前版本的证据指标和回放链路可用，但还没有证明多 Agent 在 7B 模型上提升最终 Judge 内容分。

## 真实评测协议

在相同模型、temperature、token 上限、搜索后端和 as-of 时间下，运行：

```text
A: direct_llm           单轮 LLM，无工具，统一抽取 Claim
B: search_agent         DAG + 工具 + Source/Claim，无生成阶段核验
C: evidence_agent       search_agent + Claim–Evidence 核验，固定一轮
D: full_stack           evidence_agent + IterResearch + Red-Blue + 压缩 + 共享记忆
```

最小实验：

```text
30 questions × 4 systems = 120 runs
```

更可靠实验：

```text
30 questions × 4 systems × 3 repeats = 360 runs
```

至少人工复核 20% 题目，检查自动引用蕴含结果是否正确。

## 指标与验收目标

| 指标 | 目标 | 是否已跑出真实值 |
|---|---:|---|
| Citation Entailment | ≥ 85% | 未达成；固定轨迹回放 0.180 |
| Unsupported Claim Rate | ≤ 5% | 未达成；正式 evidence 为 0.877 |
| Topic Coverage | ≥ 80% | search 0.807、evidence 0.803 |
| Source URL Validity | ≥ 95% | 本轮未配置可用价格/完整 URL 质量统计 |
| Unanswerable-task Abstention | ≥ 80% | direct 0.900、search 0.867 |
| search 相比 direct 的内容质量提升 | ≥ 10% | 未达成；Judge 分下降 3.07 分 |
| evidence 相比 search 的引用正确性提升 | ≥ 10pp | 观察到 +6.8pp，CI 跨 0 |
| P95 latency | ≤ 360s | search 323.79s、evidence 336.32s、full 396.17s |

目标未达成时不得把目标数字复制到简历，应依据消融结果继续优化。

## 推荐简历版本

### 当前可以诚实使用的版本

**AI Technology Research Agent：面向人工智能、软件系统与开源生态的证据驱动研究系统**  
**独立开发者 & 个人项目** · [GitHub](https://github.com/One-and-Done2022/AI-Technology-DeepResearchAgent)

- 基于现有 DeepResearch 编排骨架完成领域化重构，构建覆盖 AI/ML、Agent、推理基础设施、开发者工具与开源生态的技术情报研究流程，支持论文、网页、官方文档和 GitHub 多源检索。
- 设计 Claim–Evidence 证据链，将研究结论关联至稳定来源编号、原文片段、来源类型和验证状态，并通过 SQLite Evidence Store 保存可审计的结构化研究结果。
- 实现有界 IterResearch 工作区，对失败或来源不足的任务自动生成定向核验轮次；达到证据要求、轮数上限或无新增证据时提前停止。
- 自建 30 道、5 类均衡的 `TechResearchBench-Mini`，兼容 35 题/11 领域 `ResearchBench` 与 HotpotQA，支持四级能力对照、DeepSeek 外部 Judge、配对 Bootstrap 95% CI 与 Cohen's dz；70 个自动化测试通过，并完成 30 题 × 4 系统的 120 条可回放记录，其中 119 条成功生成。

### 当前正式实验可使用的版本

**AI Technology Research Agent：面向人工智能、软件系统与开源生态的证据驱动研究系统**  
**独立开发者 & 个人项目** · [GitHub](https://github.com/One-and-Done2022/AI-Technology-DeepResearchAgent)

- 构建覆盖 AI/ML、Agent、推理基础设施和开源生态的技术情报 Agent，统一检索论文、官方文档、GitHub 与网页资料，并生成带结论级引用的技术比较和选型报告。
- 自建 30 道 `TechResearchBench-Mini`，完成 `direct_llm / search_agent / evidence_agent / full_stack` 四系统配对评测，120 条记录中 119 条成功；统一计算 Topic Coverage、Reference Claim Recall、Citation Correctness、Unsupported Claim Rate 和外部 Judge 五维分。
- 在同一搜索轨迹回放中，Evidence 核验将 Citation Entailment 从 0 提升至 0.180；正式生成对比中 `evidence_agent` 的 Citation Correctness 为 0.258，相比 `search_agent` 的 0.190 观察到 +6.8pp 趋势，但 Bootstrap 95% CI 跨 0。
- 实现断点续跑、配置/数据集/Git hash、token usage、失败类型和延迟记录；正式评测 P95 为 `search_agent` 323.79s、`evidence_agent` 336.32s、`full_stack` 396.17s，定位出搜索噪声、证据绑定和多轮合成是当前主要瓶颈。
- 通过固定轨迹回放验证压缩器字符数减少 34.3%、Evidence Retention 代理值 95.2%；该结果不等同于 API input-token 降幅，后续需补充真实 tokenizer 统计。

## 面试叙述

> 原项目主要展示多 Agent 模块数量，但报告中的结论无法精确回溯到证据。我没有从零重写编排层，而是保留其异步 DAG 和模型路由，将产品重心改为 AI 技术情报：新增 Claim–Evidence 数据模型、GitHub 与论文来源、定向 IterResearch 补搜和证据核验，并建立 30 道领域 benchmark。这样可以用引用蕴含、无证据结论率、覆盖率和成本对系统做可复现实验，而不是只展示一篇看起来较长的报告。

## 与原简历的差异

原描述围绕“9 状态、多 Agent、Red-Blue、三级压缩、共享记忆”罗列模块；新描述围绕明确用户、技术情报场景、结论级证据、迭代研究和可复现评测展开。原有编排能力仍作为底层工程支撑，但不再被包装成产品的核心差异。
