# 10 小时实验 Runbook

## 运行前

在 `.env.local` 配置 Qwen、DeepSeek 和搜索服务。密钥不得提交 Git。
成本只有在配置下列每百万 tokens 单价后才会计算，否则保持 `N/A`：

```env
QWEN_INPUT_PRICE_PER_M=
QWEN_OUTPUT_PRICE_PER_M=
DEEPSEEK_INPUT_PRICE_PER_M=
DEEPSEEK_OUTPUT_PRICE_PER_M=
```

先执行：

```bash
.venv/bin/python scripts/preflight_overnight.py
```

只有 `qwen`、`judge`、`search` 和 `ready` 均为 `ok: true` 时才开始正式实验。

## 校准与主实验

先运行 1 题、四系统校准：

```bash
.venv/bin/python scripts/run_tech_benchmark.py \
  --mode run --limit 1 \
  --systems direct_llm search_agent evidence_agent full_stack \
  --config configs/benchmark.yaml \
  --concurrency 1 --orchestrator-concurrency 1 \
  --qwen-concurrency 1 --qwen-initial-concurrency 1 \
  --qwen-rpm 60 --judge-concurrency 2
```

确认记录包含 Qwen/DeepSeek 真实 usage、Claim Judge，且无 `judge_error` 后继续：

```bash
.venv/bin/python scripts/run_tech_benchmark.py \
  --mode run --limit 30 \
  --systems direct_llm search_agent evidence_agent full_stack \
  --config configs/benchmark.yaml \
  --concurrency 2 --orchestrator-concurrency 1 \
  --qwen-concurrency 2 --qwen-initial-concurrency 1 \
  --qwen-rpm 60 --judge-concurrency 4
```

同一命令可在中断后重新执行。恢复键由 `case_id + system + model + config_hash`
组成，已完成记录不会重跑。若模型、数据集或配置发生变化，应使用新的输出路径，避免混合实验版本。

## 降级与验收

- 完成不足 120 次时，仅保留四系统均完成的公共题目用于配对比较。
- 120/80/40 次分别标为 30/20/10 题实验规模；本项目当前 120 条记录已完成，但仍应称为单次冻结协议实验，不称为重复性 benchmark。
- `EVALUATION_REPORT.md` 中 95% CI 跨越 0 时，只能写“观察到提升趋势”。
- 早晨人工抽检 30 个 Claim，记录 Judge 一致率和典型分歧。
- `cost.known=false` 时不得在简历中填写推测成本。

## 版本记录

每条结果保存 Git commit、数据集 hash、配置 hash、模型 ID 和 UTC 时间。正式运行前
建议人工提交 `v0.3.0` 代码快照；本项目不会自动创建 commit 或推送远程。
