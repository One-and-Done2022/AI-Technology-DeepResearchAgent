# AI Technology DeepResearch Agent 完成路线与面试准备

本文是项目实现、评测和简历叙述的执行基准。所有百分比目标在真实实验完成前只能称为预注册目标。

## 1. 最终交付形态

```text
asyncio DAG 编排
  + 9 状态生命周期（含 FINALIZING 收口）、replan、超时降级
  + Web / GitHub / ArXiv / 官方文档工具
  + Source–Claim–Evidence 结论级证据链
  + 有界 IterResearch 定向补搜
  + Red-Blue 证据审计与修复
  + L1/L2/L3 证据保留压缩
  + SQLite + NumPy 共享记忆
  + 可回放 benchmark、统计和成本追踪
```

最终主系统命名为 `full_stack`，其能力为：

```text
full_iterresearch + Red-Blue + context compression + shared memory
```

## 2. 当前已落地

- 当前测试：`70 passed`，静态编译和 `git diff --check` 通过。
- `full_stack` 已加入 `scripts/run_tech_benchmark.py`，默认开启对抗审计、压缩、共享记忆、Evidence 和 IterResearch。
- `src/adversarial/audit.py`：输出 `ADD / MODIFY / VERIFY / DELETE` 审计事件、事实/数字/引用/覆盖维度计数、修复接受率、收敛轮数和震荡计数。
- `src/compressor/context.py`：保留引用句和高相关句，记录压缩比例、阶段统计和保留 Claim。
- `src/memory/evidence_memory.py`：使用 NumPy 向量、内容 hash 去重和相似度检索。
- `src/core/runner.py` 与 `src/orchestrator/orchestrator.py` 已将三个模块接入运行路径。

历史 Red-Blue、Compressor、Memory 代码未直接复制为不可解释的旧实现；当前版本先使用与 `Source / Claim / Evidence` 兼容的轻量实现，后续再补充更复杂的模型策略。

当前正式评测已经落盘于 `outputs/tech_benchmark_openalex_formal_current/`：30 题 × 4 系统共 120 条记录，119 条生成成功。正式结果显示 Evidence 指标存在小幅改善趋势，但尚未达到预注册的 +12pp / -10pp 目标；因此目标数字仍保持为预注册目标。

## 3. 必须完成的实验

### 3.1 系统配置

```text
direct_llm
search_agent
evidence_agent
full_stack
```

至少执行 `30 题 × 4 系统 = 120 runs`。其中 `full_stack` 同时开启 IterResearch、Red-Blue、压缩和 Memory；若要验证模块独立贡献，再执行：

```text
full_stack_without_redblue
full_stack_without_compressor
full_stack_without_memory
```

### 3.2 公平性约束

- 固定数据集 hash、模型 ID、温度、最大输出 token 和 `as_of` 日期。
- 搜索消融使用同一 Search Trace，避免把搜索随机性误判为模块收益。
- 所有系统统一后处理 Claim；`direct_llm` 的证据指标为 `null`，不是 0。
- Judge 不接收系统名称，只接收 query、report、claims 和 sources。
- 每题完成即写 JSONL，主键为 `case_id + system + model + config_hash`。

### 3.3 核心指标

```text
Citation Entailment = (supported + 0.5 × partially_supported) / cited_claims
Unsupported Claim Rate = (unknown + contradicted) / verifiable_claims
Token Reduction = 1 - compressed_tokens / original_tokens
Evidence Retention = retained_important_evidence / original_important_evidence
```

同时报告 Topic Coverage、Reference Claim Recall、DeepSeek 五维内容分、成功率、重规划恢复率、P50/P95 延迟、输入/输出 token、工具调用和单题成本。

### 3.4 预注册目标

```text
内容质量提升约 12%
Citation Entailment 提升约 12 个百分点
Unsupported Claim Rate 降低约 10 个百分点
输入 token 减少约 35%
Evidence Retention 不低于 93%
P95 延迟不超过 360 秒
```

达到目标后才能将简历中的“预注册目标”改为真实结果，并附带样本量、95% CI 和 Cohen’s dz。

## 4. 执行顺序

1. 冻结 `TechResearchBench-Mini` v0.2：补齐 30 题原子 Claim、证据摘录和允许来源。
2. 先运行 `1–5 题 × 4 系统` 开发校准，检查 JSON、Claim、审计、压缩、Memory 和断点续跑。
3. 使用同一协议运行 `30 题 × 4 系统`。（已完成）
4. 已完成固定轨迹的 Evidence、Red-Blue、压缩和 Memory 回放；下一轮再加跑独立的生成级配置消融。
5. 抽检至少 20% Claim，计算 Judge 与人工的一致率。（当前收口任务）
6. 修复来源排序、Claim 绑定和 full_stack 超时后，再跑第二个 repeat。
7. 接入公开 DeepResearch benchmark，验证 TechResearchBench 之外的泛化能力。
8. 根据正式结果更新 `docs/EVALUATION.md`、README 和简历。（当前版本已更新）

## 5. 面试回答基线

### 为什么 `direct_llm` 可能更高？

7B 模型在短回答上较稳定，但长链路 Agent 会引入搜索噪声、上下文膨胀、来源丢失和合成退化。这个结果说明系统瓶颈在链路设计，不等于 Evidence 方法没有价值。

### 如何证明 Red-Blue 有用？

固定同一份初始报告，比较开启和关闭 Red-Blue 的 Citation Entailment、Unsupported Claim Rate、修复接受率、收敛轮数和人工一致率。

### 如何证明压缩有效？

不能只报告 token 降低；必须同时报告 `Token Reduction` 和 `Evidence Retention`，否则可能只是删除了信息。

### 为什么 `direct_llm` 的证据指标是 N/A？

它没有外部来源，因此没有可计算的 citation entailment。`null` 表示不适用，0 才表示适用但没有命中。

### 85% 到 95% 是什么？

这是结构化 JSON 响应解析成功率，不是事实准确率、研究成功率或报告质量提升率；如果无法在新链路中复现，应从简历中删除该数字。

### 为什么不直接做 RL？

当前主要瓶颈是搜索召回、证据绑定、上下文管理和报告合成。先完成可解释的模块消融，再考虑 Search-R1/DeepResearcher 风格训练，避免只有训练脚本而没有可信收益。

### 如果 `full_stack` 仍不如 `direct_llm`？

如实报告，重点解释失败来源：搜索质量、上下文压缩、引用绑定、模型规模和延迟预算。能定位瓶颈并提出下一步实验，比虚构正向数字更有说服力。

