# AI Technology Research Agent

面向人工智能、软件系统与开源生态的证据驱动研究系统。

[GitHub Repository](https://github.com/One-and-Done2022/AI-Technology-DeepResearchAgent)

该版本基于仓库原有 DeepResearch Agent 编排骨架重构，保留异步 DAG 调度、模型路由和基础工具层，重点新增：

- AI/软件技术研究工作流；
- Claim–Evidence 结论级证据链；
- 有界 IterResearch 补充研究轮次；
- GitHub、论文、官方文档和网页多源研究；
- 引用蕴含、无证据结论率和来源质量评测；
- 可复现的 `TechResearchBench-Mini`。

## 项目定位

系统主要处理以下问题：

- AI/ML 模型、论文和训练方法研究；
- LLM 与 Agent 技术路线比较；
- 推理框架、MLOps 和云基础设施选型；
- 软件工程与开发者工具分析；
- GitHub 开源项目技术尽调。

它不是普通的“搜索后生成长报告”：每个重要结论需要关联稳定的 `[S#]` 来源编号、证据片段、来源类型和验证状态。

## 核心流程

```text
Technology Query
    ↓
Domain-aware DAG Planner
    ↓
Parallel Research Workers
    ├── Web Search / Browser
    ├── ArXiv / OpenAlex / Semantic Scholar
    ├── GitHub Repository Reader
    └── Calculator / Sandbox / File Reader
    ↓
Claim–Evidence Normalization
    ↓
IterResearch Gap Detection
    ├── 来源不足 → 定向补搜
    ├── 任务失败 → 证据核验
    └── 无新增证据 → 提前停止
    ↓
Evidence-grounded Synthesis
    ↓
Claim Verification + Structured Report
```

## Claim–Evidence 数据模型

```text
Source
  source_id, url, title, source_type, quote,
  published_at, retrieved_at, content_hash, quality_score

Claim
  claim_id, statement, citations, evidence,
  verification_status, confidence

VerificationStatus
  supported | partially_supported | contradicted | unknown
```

证据数据同时写入 Markdown 报告、结构化 JSON 和 SQLite Evidence Store。

## 主要改造

### 1. 领域化研究规划

Planner 优先拆分论文、官方文档、实现证据和量化核验任务。涉及性能、成本、排名或趋势时，要求生成验证任务。

### 2. 有界 IterResearch

每轮研究后检查各子任务的来源数量。失败或来源不足的任务会生成有限数量的补充核验任务；达到最大轮数、证据满足或无新增证据时停止，避免无限搜索。

### 3. GitHub 技术尽调

`github_reader` 支持读取：

- 仓库描述、语言和主题；
- stars、forks 和 issue 数；
- README；
- 许可证；
- 创建、更新与 push 时间；
- 最新 Release；
- archived 状态。

无 `GITHUB_TOKEN` 也可使用公开 API，但限流更严格。

### 4. 证据优先报告生成

Summarizer 使用统一 Evidence Catalog，只允许引用目录中存在的 `[S#]`，不再要求固定 3000 字。证据不足时必须显式标注，不能通过扩写补足篇幅。

### 5. 可审计指标

自动评测指标包括：

```text
Citation Coverage
Citation Entailment
Unsupported Claim Rate
Contradicted Claim Rate
Topic Coverage
Reference Claim Recall
Primary Source Rate
Source Quality
Abstention Accuracy
Latency / Tool Calls
```

自动引用蕴含采用保守的词项覆盖与数值一致性检查，最终简历数据需要配合人工抽检；它不被描述为完整事实真值判定。

## 快速开始

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e '.[dev]'
```

复制需要的环境变量到 `.env.local`：

```bash
cp .env.template .env.local
```

至少配置一个 LLM 后端和一个搜索后端；全部连接配置集中在 `.env.local`。

项目目录和每个配置键的含义见 [`docs/PROJECT_STRUCTURE.md`](docs/PROJECT_STRUCTURE.md)。仓库只保留 `configs/default.yaml` 和 `configs/smoke.yaml` 两份 YAML。

运行单条技术研究：

```bash
.venv/bin/python scripts/run_single.py \
  --query "对比 vLLM、SGLang 与 TensorRT-LLM 的调度、硬件支持和部署复杂度"
```

输出目录包含：

```text
report_*.md                  # 用户可读报告
techresearch-*.json          # claims、sources、rounds 和指标
run_*.log                    # 可回放执行日志
```

## TechResearchBench-Mini

当前领域集包含 30 道题，五类各 6 道：

| 类别 | 数量 |
|---|---:|
| AI/ML | 6 |
| LLM/Agent | 6 |
| 推理与系统基础设施 | 6 |
| 软件工程与开发者工具 | 6 |
| 开源生态与技术选型 | 6 |

其中包含来源冲突、虚构技术核验和证据不足拒答任务。

运行真实三系统对照：

```bash
.venv/bin/python scripts/run_tech_benchmark.py \
  --mode run \
  --systems direct single_round evidence \
  --limit 30
```

重新评分已有结果：

```bash
.venv/bin/python scripts/run_tech_benchmark.py \
  --mode evaluate \
  --input outputs/tech_benchmark/results.jsonl
```

脚本输出按系统和类别聚合的指标，并对公共题目计算配对 Bootstrap 95% CI。

## 验证

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src evaluation scripts tests
```

当前离线验证结果：

```text
15 passed
compileall passed
targeted mypy passed (10 new evidence/research/evaluation files)
GitHub Reader live smoke passed (metadata, README, license, latest release)
```

`evaluation/fixtures/tech_benchmark_smoke.jsonl` 只验证评分和统计脚本，不能作为真实模型效果或简历指标。由于仓库环境未配置真实 API Key/本地 vLLM 服务，联网的 30 题对照结果需要在配置模型和搜索服务后运行。

## 目录

```text
src/
├── core/                  # 配置加载、模块装配、运行与序列化
├── evidence/              # schemas、抽取、核验、来源质量、SQLite Store
├── research/              # IterResearch workspace
├── orchestrator/          # DAG 并发与研究轮次
├── planner/               # 技术问题拆解与 DAG
├── agents/                # Researcher / evidence-grounded Summarizer
├── tools/                 # Web、Browser、ArXiv、GitHub、计算、文件
├── models/                # 多后端 LLM 路由
└── utils/                 # 环境变量与可选追踪

evaluation/
├── datasets/tech_research_mini.jsonl
├── benchmarks/tech_research_bench.py
└── metrics/claim_metrics.py

scripts/
├── run_single.py
└── run_tech_benchmark.py

docs/
├── PROJECT_STRUCTURE.md
└── STAR_AND_RESUME.md
```

## 简历与 STAR

项目的目标、可量化验收条件、真实结果填写规则和简历模板见 `docs/STAR_AND_RESUME.md`。
