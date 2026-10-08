# 公平重评执行状态

最后核对：2026-10-03

## 已完成

- 当前会话工作目录确认：`/home/liuchenyang/deepresearch-agent`。
- Qwen2.5-7B API 预检通过，模型 ID 为 `Qwen/Qwen2.5-7B-Instruct`。
- DeepSeek Judge API 预检通过，模型 ID 为 `deepseek-ai/DeepSeek-V4-Flash`。
- `evaluation/judge.py` 的报告评分接口已接收 `as_of`、`answerable`、`expected_topics`、`required_claims`、`sources` 和 `claims`；不传上下文的旧调用仍兼容。
- Claim 抽取会跳过 Markdown 标题、表格行和表格分隔线，避免结构文本污染 Claim 分母。
- 已增加 `rejudge` 模式，只重评已有报告，不重新生成、不调用搜索：

  ```text
  outputs/tech_benchmark_rejudged/results.jsonl
  ```

- 已完成 20 条历史报告的带 benchmark 上下文重评：20/20 有 `judge_revision=benchmark_context_v2`，Judge 错误数为 0。
- 已生成逐题四系统报告对照包：

  ```text
  outputs/report_comparison_rejudged/
  ```

- 全量测试：`53 passed`。
- 最新证据链与审计修复后全量测试：`59 passed`；无引用 Claim 不再被直接删除，而是保留正文并记录 `VERIFY` 事件；候选 Citation 可由来源标题或摘录绑定，但最终 `supported` 仍只由摘录核验决定；summary 会聚合审计、压缩和记忆运行时指标。
- 已完成一次不依赖搜索的真实 Qwen LLM Red-Blue smoke：2 次 JSON 响应均解析成功，解析成功率 `1.0`，识别 1 个 numeric 问题并执行 `MODIFY`，实际 usage 为 `739 input / 212 output tokens`。该结果只验证模块接口，不属于正式研究 benchmark。
- 使用 `configs/smoke.yaml` 完成 1 题 × 4 系统 Mock Search 工程 smoke：四系统均成功落盘，`full_stack` 记录 `compression_ratio=0.506`、`evidence_retention=1.0`、`memory_deduplicated=7` 和 `oscillation_count=1`。该结果只验证工程链路，不用于质量提升结论。
- 新增 `configs/benchmark.yaml`，固定外部 API 评测的模型输出预算、研究轮数和全局超时。
- OpenAlex 配额耗尽时新增 arXiv Atom API 降级；OpenAlex 可用时仍优先使用 OpenAlex。
- 全局超时/部分报告不再进入质量均值和配对比较。
- 1 题四系统校准 v3 已完成：

  ```text
  outputs/tech_benchmark_openalex_calibrated_v3/
  ```

  校准只验证接口和指标链，不是正式效果结论。观察到：`search_agent` 6 sources/15 claims、`evidence_agent` 7 sources/22 claims、`full_stack` 12 sources/13 claims；full_stack 的 `citation_coverage=1.0`、`evidence_retention=1.0`、压缩比例约 `0.604`，但外部 Judge 的 `citation_correctness=0.154`、`unsupported_claim_rate=0.769`，说明“有引用”不等于“引用正确”，正式实验仍需 Claim 抽检和来源质量控制。

- 1 题四系统校准 v5 已完成：

  ```text
  outputs/tech_benchmark_openalex_calibrated_v5/
  ```

  该轮使用 `max_plan_tasks=4` 和保守审计策略。四个系统均成功落盘；内容 Judge 分数为 `6.0/6.4/2.6/5.0`，墙钟时间约为 `9.7/144.8/202.4/376.0s`。`full_stack` 的 `compression_ratio=0.587`、`evidence_retention=1.0`，但 `citation_entailment=0`、`unsupported_claim_rate=1.0`，仍属于开发校准，不是正式效果结论。`n=1`，所有配对统计均标记 `insufficient_n=true`。

## 当前阻塞

博查 API 预检仍可能返回：

```text
You do not have enough money or package quota
```

OpenAlex 在本机共享免费额度耗尽时也会返回 `Insufficient budget`；当前已通过 arXiv fallback 保证学术类查询仍有来源，但正式结果必须记录实际后端，不能把 OpenAlex 和 fallback 结果混为一组。

旧 commit `317a0d4` 的 Red-Blue、上下文压缩和共享记忆模块已在临时目录做隔离导入检查；历史初始化路径长时间阻塞，且依赖/API 与当前主线不同，暂未得到可复现的旧模块消融结果。当前不使用历史简历中的“85% → 95%”数字。

## 结果解释边界

`outputs/tech_benchmark_dev_v2/` 是先前生成的 5 题 × 4 系统记录；`outputs/tech_benchmark_rejudged/` 只是对同一批报告重新评分，不是新的 20 次生成实验。

因此当前可以证明的是：

1. 公平 Judge 接口和统一报告对照链已经可运行；
2. 客观规则指标、来源指标、Claim–Evidence 指标和工程指标都能从 JSONL 重新聚合；
3. 现有历史报告中的搜索噪声、超时、空来源和内容退化是真实生成问题，不能全部归因于 Judge。

当前不能宣称：

- 搜索、Evidence 或 IterResearch 已经提升内容质量；
- 旧版 Red-Blue、压缩或记忆已带来确定收益；
- 已完成 10 题或 30 题真实四系统 pilot。
- 预注册目标（内容质量 +12%、Citation Entailment +12pp 等）已经达成。

## 余额恢复后的续跑

先重新执行：

```bash
PYTHONPATH=. .venv/bin/python scripts/preflight_overnight.py
```

确认搜索服务可用后，使用固定 benchmark 配置启动四系统校准：

```bash
PYTHONPATH=. .venv/bin/python scripts/run_tech_benchmark.py \
  --mode run \
  --limit 10 \
  --systems direct_llm search_agent evidence_agent full_stack \
  --config configs/benchmark.yaml \
  --concurrency 2 \
  --orchestrator-concurrency 1 \
  --qwen-concurrency 2 \
  --qwen-initial-concurrency 1 \
  --qwen-rpm 60 \
  --judge-concurrency 4 \
  --output outputs/tech_benchmark_calibration/results.jsonl \
  --summary outputs/tech_benchmark_calibration/summary.json \
  --report outputs/tech_benchmark_calibration/PILOT_REPORT.md \
  --comparison-dir outputs/report_comparison_calibration
```

脚本按 `case_id + system + model + config_hash` 断点续跑，失败记录不会被静默删除。
