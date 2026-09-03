# AI Technology Research Agent：STAR 与简历基准

版本日期：2026-08-30

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
- 新增 direct / single_round / evidence 三系统对比与配对 Bootstrap 95% CI；
- 新增自动化单元和集成测试。

### R — Result

目前已经验证的结果：

| 项目 | 已验证结果 |
|---|---:|
| 领域评测题数 | 30 |
| 评测类别 | 5 |
| 每类题数 | 6 |
| 自动化测试 | 15 passed |
| Python 静态编译 | passed |
| 新增 evidence/research/evaluation 文件定向 mypy | 10 files passed |
| Evidence SQLite round-trip | passed |
| Researcher → Source → Summarizer → Claim 集成流 | passed |
| IterResearch follow-up/stop 条件 | passed |
| GitHub Reader 公开 API 实测 | metadata/README/license/release passed |
| 三系统评分与 Bootstrap 脚本 | smoke passed |

尚未验证、不得写成简历成果：

- 真实 30 题的引用蕴含率；
- 无证据结论率的实际下降；
- 相比单轮 LLM 或 single_round 的质量提升；
- P50/P95 延迟、token 和 API 成本；
- 真实链接访问成功率；
- 人工评分与自动 Judge 的一致性。

原因：当前运行环境未配置 LLM/Search API Key，本地 vLLM 服务也未启动。`evaluation/fixtures/tech_benchmark_smoke.jsonl` 是合成脚本夹具，不是模型实验。

## 真实评测协议

在相同模型、temperature、token 上限、搜索后端和 as-of 时间下，运行：

```text
A: direct   单轮 LLM，不使用工具
B: single_round   单轮 DAG 工作流，关闭 IterResearch
C: evidence Claim–Evidence + IterResearch 版本
```

最小实验：

```text
30 questions × 3 systems = 90 runs
```

更可靠实验：

```text
30 questions × 3 systems × 3 repeats = 270 runs
```

至少人工复核 20% 题目，检查自动引用蕴含结果是否正确。

## 指标与验收目标

| 指标 | 目标 | 是否已跑出真实值 |
|---|---:|---|
| Citation Entailment | ≥ 85% | 否 |
| Unsupported Claim Rate | ≤ 5% | 否 |
| Topic Coverage | ≥ 80% | 否 |
| Source URL Validity | ≥ 95% | 否 |
| Unanswerable-task Abstention | ≥ 80% | 否 |
| 相比 direct 的综合提升 | ≥ 20% | 否 |
| P95 latency | ≤ 180s（可按模型调整） | 否 |

目标未达成时不得把目标数字复制到简历，应依据消融结果继续优化。

## 推荐简历版本

### 当前可以诚实使用的版本

**AI Technology Research Agent：面向人工智能、软件系统与开源生态的证据驱动研究系统**  
**独立开发者 & 个人项目** · [GitHub](https://github.com/One-and-Done2022/AI-Technology-DeepResearchAgent)

- 基于现有 DeepResearch 编排骨架完成领域化重构，构建覆盖 AI/ML、Agent、推理基础设施、开发者工具与开源生态的技术情报研究流程，支持论文、网页、官方文档和 GitHub 多源检索。
- 设计 Claim–Evidence 证据链，将研究结论关联至稳定来源编号、原文片段、来源类型和验证状态，并通过 SQLite Evidence Store 保存可审计的结构化研究结果。
- 实现有界 IterResearch 工作区，对失败或来源不足的任务自动生成定向核验轮次；达到证据要求、轮数上限或无新增证据时提前停止。
- 自建 30 道、5 类均衡的 `TechResearchBench-Mini`，实现 direct/single_round/evidence 三系统对比、引用蕴含与无证据结论率评分、配对 Bootstrap 95% CI；补充 15 个自动化测试并全部通过。

### 跑完真实 benchmark 后替换为

**AI Technology Research Agent：面向人工智能、软件系统与开源生态的证据驱动研究系统**  
**独立开发者 & 个人项目** · [GitHub](https://github.com/One-and-Done2022/AI-Technology-DeepResearchAgent)

- 构建覆盖 AI/ML、Agent、推理基础设施和开源生态的技术情报 Agent，统一检索论文、官方文档、GitHub 与网页资料，并生成带结论级引用的技术比较和选型报告。
- 设计 Claim–Evidence 证据链与有界 IterResearch 工作区，通过定向补搜和数值一致性核验，将引用蕴含率由 **[A]%** 提升至 **[B]%**，无证据结论率降低 **[C]** 个百分点。
- 自建 30 道 `TechResearchBench-Mini`，对比单轮 LLM、原始 DAG Agent 和证据驱动版本；综合质量提升 **[D]%**，配对 Bootstrap 95% CI 为 **[L, U]**。
- 实现 GitHub/论文/网页多源工具和结构化运行追踪，在平均 **[K]** 次工具调用、P95 **[T]** 秒延迟下完成研究，15 个自动化测试全部通过。

## 面试叙述

> 原项目主要展示多 Agent 模块数量，但报告中的结论无法精确回溯到证据。我没有从零重写编排层，而是保留其异步 DAG 和模型路由，将产品重心改为 AI 技术情报：新增 Claim–Evidence 数据模型、GitHub 与论文来源、定向 IterResearch 补搜和证据核验，并建立 30 道领域 benchmark。这样可以用引用蕴含、无证据结论率、覆盖率和成本对系统做可复现实验，而不是只展示一篇看起来较长的报告。

## 与原简历的差异

原描述围绕“9 状态、多 Agent、Red-Blue、三级压缩、共享记忆”罗列模块；新描述围绕明确用户、技术情报场景、结论级证据、迭代研究和可复现评测展开。原有编排能力仍作为底层工程支撑，但不再被包装成产品的核心差异。
