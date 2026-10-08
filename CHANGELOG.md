# Changelog

## 0.3.0 - 2026-09-16

- 将评测系统拆分为 `direct_llm`、`search_agent`、`evidence_agent` 和
  `full_iterresearch`，用于隔离搜索、证据核验和迭代补搜的贡献。
- 增加细粒度 Claim 类型、统一后处理、外部 DeepSeek 报告/Claim Judge。
- 增加真实 API usage、成本字段、逐条 JSONL、断点续跑和并发控制。
- 将内容质量与证据质量分开汇总，增加配对 Bootstrap 95% CI 和 Cohen's dz。

## 0.2.0

- 完成 AI Technology Research Agent 的领域证据链、IterResearch 和
  TechResearchBench-Mini 初版。
