# 项目目录与配置说明

本文对应精简后的 AI Technology Research Agent。仓库只保留两个运行入口、两份 YAML 配置和一套领域评测。

## 顶层目录

```text
deepresearch-agent/
├── configs/                 # 非敏感运行参数
│   ├── default.yaml         # 真实 API 默认配置
│   └── smoke.yaml           # 本地 vLLM + Mock 工具冒烟配置
├── docs/                    # 架构、STAR 和简历材料
├── evaluation/              # TechResearchBench 与自动评分
├── scripts/                 # 用户运行入口
├── src/                     # 产品源码
├── tests/                   # pytest 自动化测试和 vLLM 启动脚本
├── .env.template            # 连接信息模板，不包含真实凭证
├── pyproject.toml           # 包、依赖和命令入口
└── README.md                # 项目介绍和快速开始
```

`outputs/` 和 `data/` 是运行时生成目录，不应提交报告、数据库或日志。

## `src/` 源码目录

| 目录 | 含义 | 核心文件 |
|---|---|---|
| `agents/` | Agent 行为层；执行工具循环与最终报告合成 | `researcher.py`, `summarizer.py` |
| `core/` | 模块装配、配置加载、单次研究运行与输出序列化 | `runner.py` |
| `evidence/` | Source/Claim 模型、来源归一化、证据核验和 SQLite 存储 | `schemas.py`, `extractor.py`, `verifier.py`, `store.py` |
| `models/` | OpenAI-compatible 客户端和后端路由 | `model_router.py`, `vllm_policy.py` |
| `orchestrator/` | DAG 分层并发、超时、重规划、研究轮次与降级报告 | `orchestrator.py`, `agent_pool.py`, `schemas.py` |
| `planner/` | 将技术问题拆成搜索、分析、验证任务 | `planner.py`, `dag.py` |
| `research/` | IterResearch 工作区；判断是否补搜或停止 | `workspace.py` |
| `tools/` | Web、浏览器、论文、GitHub、计算、沙箱、文件和笔记工具 | `web_search.py`, `github_reader.py` 等 |
| `utils/` | 环境变量加载和可选追踪 | `env_config.py`, `tracing.py` |

主数据流：

```text
Query
  → Planner DAG
  → Orchestrator/Researcher
  → Tool observations
  → Source + Claim
  → IterResearch gap check
  → Summarizer [S#]
  → EvidenceVerifier
  → Markdown + JSON + SQLite
```

## `evaluation/` 评测目录

```text
evaluation/
├── benchmarks/tech_research_bench.py    # 数据加载、单题评分、分组汇总
├── datasets/tech_research_mini.jsonl    # 30 道、5 类领域题
├── fixtures/tech_benchmark_smoke.jsonl  # 仅测试评分脚本，不能当模型结果
└── metrics/
    ├── claim_metrics.py                  # 引用、来源、覆盖、拒答、效率指标
    └── stats.py                          # Bootstrap CI 与效应量
```

## `scripts/` 入口

| 命令 | 用途 |
|---|---|
| `run-research` / `scripts/run_single.py` | 执行一个研究问题，输出 Markdown 和结构化 JSON |
| `run-tech-benchmark` / `scripts/run_tech_benchmark.py` | 运行或重评 direct/single_round/evidence 对照实验 |

## YAML 配置原则

YAML 只保存非敏感行为参数；API Key、Base URL、模型名和工具连接信息放在 `.env.local`。

配置优先级：

```text
源码默认值 < .env/.env.local 连接参数 < YAML backend/module sampling 覆盖
```

### `model`

| 键 | 含义 |
|---|---|
| `backend` | 默认 LLM 后端，例如 `deepseek` 或 `vllm` |
| `backend_sampling.<backend>` | 该后端的默认 temperature/max_tokens/top_p |
| `backend_sampling.modules.planner` | Planner 结构化 JSON 参数 |
| `backend_sampling.modules.solver` | Researcher 参数 |
| `backend_sampling.modules.summarizer` | 最终报告参数 |
| `backend_mapping` | 将 planner/solver/summarizer 映射到具体后端 |

若三个模块使用同一服务，保持三项映射相同即可；只有确实需要异构模型时才分别修改。

### `orchestrator`

| 键 | 默认值 | 含义 |
|---|---:|---|
| `max_concurrent` | 5 | 同时执行的子任务数 |
| `global_timeout_seconds` | 600 | 单次研究总超时 |
| `max_replan_rounds` | 2 | 失败任务允许的 LLM 重规划次数 |

### `research`

| 键 | 默认值 | 含义 |
|---|---:|---|
| `enabled` | true | 是否启用 IterResearch 补充研究 |
| `max_rounds` | 2 | 初始研究加补搜的最大轮数 |
| `min_sources_per_task` | 2 | 每个任务要求的去重来源数 |
| `max_followup_tasks` | 3 | 每轮最多生成的定向核验任务 |
| `max_tool_calls` | 6 | 单个 Researcher 的工具调用预算 |

### `evidence`

| 键 | 默认值 | 含义 |
|---|---:|---|
| `enabled` | true | 是否持久化结构化证据 |
| `db_path` | `data/evidence.db` | SQLite 路径 |
| `support_threshold` | 0.22 | claim 与证据达到 supported 的覆盖阈值 |
| `partial_threshold` | 0.08 | partially_supported 阈值 |

这两个阈值属于离线保守 verifier，需要用人工标注样本校准，不能直接解释为事实正确率。

### `tools`

| 键 | 默认值 | 含义 |
|---|---:|---|
| `mock_mode` | false | 同时切换 Web/Browser/ArXiv/GitHub 到确定性 Mock |
| `github_timeout_seconds` | 20 | GitHub API 总超时 |

其他工具连接参数统一由环境变量管理，不再维护重复的 `configs/tools/*.yaml`。

## `.env.local` 配置

首先复制：

```bash
cp .env.template .env.local
```

默认 DeepSeek + 博查组合至少需要：

```dotenv
DEEPSEEK_API_KEY=...
SEARCH_BACKEND=bocha
BOCHA_API_KEY=...
ARXIV_READER_BACKEND=openalex
```

可选：

- `GITHUB_TOKEN`：提高 GitHub API 限流额度；
- `OPENALEX_EMAIL`：提高 OpenAlex polite pool 配额；
- `BROWSER_TIMEOUT`：网页读取超时；
- `LANGSMITH_*`：开启执行追踪。

## 两份 YAML 的使用方式

真实 API：

```bash
.venv/bin/python scripts/run_single.py --config configs/default.yaml --query "..."
```

本地 vLLM + Mock 工具：

```bash
.venv/bin/python scripts/run_single.py --config configs/smoke.yaml --query "..."
```

`smoke.yaml` 只能验证流程和格式，不能产生简历质量指标。
