#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
src/core/runner.py
================================================================================
DeepResearch Agent 核心运行逻辑。

本模块包含初始化所有模块和执行完整研究流程的核心函数，
供 scripts/ 和 evaluation/ 统一调用，避免 evaluation/ 反向依赖 scripts/。

对外接口:
    - load_config(config_path) -> dict
    - initialize_modules(config) -> dict
    - run_research(query, config, modules) -> str
    - save_report(report, query, output_dir) -> str
================================================================================
"""

from __future__ import annotations

import logging
import os
import re
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

# 将项目根目录加入 sys.path，确保 src 包可导入
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------
def setup_logging(log_level: str = "INFO") -> None:
    """配置全局日志格式与级别。"""
    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


# ---------------------------------------------------------------------------
# 配置加载
# ---------------------------------------------------------------------------
def load_config(config_path: str | None = None) -> dict:
    """
    加载 YAML 配置文件。

    若未指定路径，默认加载 configs/default.yaml。
    """
    if config_path is None:
        config_path = os.path.join(PROJECT_ROOT, "configs", "default.yaml")

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件未找到: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config


# ---------------------------------------------------------------------------
# 工具工厂
# ---------------------------------------------------------------------------
def _create_tools_factory(config: dict):
    """创建工具工厂函数，返回 Agent 可用的工具列表。"""
    tools_cfg = config.get("tools", {})
    mock_mode = bool(tools_cfg.get("mock_mode", False))

    from src.tools import (
        WebSearchTool,
        MockWebSearchTool,
        ArxivReaderTool,
        BrowserTool,
        MockBrowserTool,
        FileReaderTool,
        CodeSandboxTool,
        CalculatorTool,
        NotepadTool,
        GitHubReaderTool,
        MockGitHubReaderTool,
    )

    tools = {}

    # 1. web_search
    if mock_mode:
        tools["web_search"] = MockWebSearchTool()
    else:
        tools["web_search"] = WebSearchTool()

    # 2. browser
    if mock_mode:
        tools["browser"] = MockBrowserTool()
    else:
        tools["browser"] = BrowserTool()

    # 3. arxiv_reader
    tools["arxiv_reader"] = ArxivReaderTool(use_mock=mock_mode)

    # 4. file_reader（不限制目录）
    tools["file_reader"] = FileReaderTool(allowed_base_dir=None)

    # 5. code_sandbox
    tools["code_sandbox"] = CodeSandboxTool(use_mock=mock_mode)

    # 6. calculator
    tools["calculator"] = CalculatorTool()

    # 7. notepad
    tools["notepad"] = NotepadTool()

    # 8. GitHub repository intelligence
    github_timeout = int(tools_cfg.get("github_timeout_seconds", 20))
    tools["github_reader"] = (
        MockGitHubReaderTool(timeout=github_timeout)
        if mock_mode
        else GitHubReaderTool(timeout=github_timeout)
    )

    # 返回列表形式（AgentPool 和 Agent 构造函数需要 list）
    return list(tools.values())


# ---------------------------------------------------------------------------
# 模块初始化
# ---------------------------------------------------------------------------
def initialize_modules(config: dict) -> dict[str, Any]:
    """
    根据配置初始化所有核心模块。

    Args:
        config: 全局配置字典。

    返回一个包含各模块实例的字典。
    """
    logger = logging.getLogger("runner")
    logger.info("正在初始化核心模块...")

    modules: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # 多后端 LLM 初始化（从 .env + configs/default.yaml 读取配置）
    # ------------------------------------------------------------------
    from src.models.model_router import ModelRouter

    model_cfg = config.get("model", {})
    default_backend = model_cfg.get("backend", "vllm")
    backend_mapping = model_cfg.get("backend_mapping", {})
    backend_sampling = model_cfg.get("backend_sampling", {})

    # 辅助函数：根据模块名获取采样参数覆盖
    def _get_sampling_kwargs(module_name: str, backend_name: str) -> dict:
        """合并后端全局默认 + 模块级覆盖参数。"""
        kwargs = {}
        # 1. 后端全局默认
        if backend_name in backend_sampling:
            kwargs.update(backend_sampling[backend_name])
        # 2. 模块级覆盖（优先级更高）
        module_overrides = backend_sampling.get("modules", {}).get(module_name, {})
        kwargs.update(module_overrides)
        return kwargs

    # 默认后端（所有模块共用）
    default_kwargs = _get_sampling_kwargs("default", default_backend)
    default_policy = ModelRouter.create_backend(default_backend, **default_kwargs)
    modules["default_policy"] = default_policy
    logger.info(f"[LLM] 默认后端已加载: {default_backend} ({default_kwargs})")

    # 多后端分工：不同模块用不同后端 + 不同采样参数
    for module_name, backend_name in backend_mapping.items():
        kwargs = _get_sampling_kwargs(module_name, backend_name)
        modules[f"{module_name}_policy"] = ModelRouter.create_backend(backend_name, **kwargs)
        logger.info(f"[LLM] {module_name} → 后端={backend_name}, 采样={kwargs}")

    # 若未配置分工，所有模块回退到 default_policy
    # ------------------------------------------------------------------

    # Adaptive Planner（Orchestrator 依赖 Planner，先初始化）
    from src.planner.planner import Planner
    from src.planner.budget_tracker import BudgetTracker

    planner_policy = modules.get("planner_policy", default_policy)
    budget_tracker = BudgetTracker()
    planner = Planner(policy=planner_policy, budget_tracker=budget_tracker)
    modules["planner"] = planner
    logger.info("Planner 模块已初始化")

    evidence_cfg = config.get("evidence", {})
    evidence_store = None
    from src.evidence.extractor import EvidencePipeline
    from src.evidence.verifier import EvidenceVerifier

    evidence_pipeline = EvidencePipeline(
        EvidenceVerifier(
            support_threshold=float(evidence_cfg.get("support_threshold", 0.22)),
            partial_threshold=float(evidence_cfg.get("partial_threshold", 0.08)),
        )
    )
    if evidence_cfg.get("enabled", True):
        from src.evidence.store import EvidenceStore

        evidence_store = EvidenceStore(evidence_cfg.get("db_path", "data/evidence.db"))
        modules["evidence_store"] = evidence_store
        logger.info("[Evidence] Claim-Evidence Store 已初始化")

    # Tools（真实工具或 Mock 工具）
    tools_list = _create_tools_factory(config)
    modules["tools"] = tools_list
    logger.info(f"Tools 模块已初始化（共 {len(tools_list)} 个工具）")

    # Multi-Agent Orchestrator
    from src.orchestrator.orchestrator import Orchestrator
    from src.orchestrator.agent_pool import AgentPool

    agent_pool = AgentPool(
        policy_factory=lambda: modules.get("solver_policy", default_policy),
        tools_factory=lambda: list(modules["tools"]),
        max_idle=3,
        agent_kwargs={
            "max_tool_calls": int(config.get("research", {}).get("max_tool_calls", 6)),
            "support_threshold": float(evidence_cfg.get("support_threshold", 0.22)),
            "partial_threshold": float(evidence_cfg.get("partial_threshold", 0.08)),
        },
    )
    modules["agent_pool"] = agent_pool

    orchestrator = Orchestrator(
        planner=planner,
        agent_pool=agent_pool,
        budget_tracker=budget_tracker,
        summarizer_policy=modules.get("summarizer_policy", default_policy),
        evidence_store=evidence_store,
        evidence_pipeline=evidence_pipeline,
    )
    modules["orchestrator"] = orchestrator
    logger.info("Orchestrator 模块已初始化")

    return modules


# ---------------------------------------------------------------------------
# 研究流程主函数
# ---------------------------------------------------------------------------
async def run_research_report(query: str, config: dict, modules: dict[str, Any]):
    """Run the workflow and return the structured ResearchReport."""
    logger = logging.getLogger("runner")
    logger.info(f"开始研究，查询: {query[:80]}...")
    orchestrator = modules["orchestrator"]
    from src.orchestrator.schemas import RunConfig

    research_cfg = config.get("research", {})
    run_cfg = RunConfig(
        max_concurrent=config.get("orchestrator", {}).get("max_concurrent", 5),
        global_timeout_seconds=config.get("orchestrator", {}).get("global_timeout_seconds", 600),
        max_replan_rounds=config.get("orchestrator", {}).get("max_replan_rounds", 3),
        enable_iterative_research=research_cfg.get("enabled", True),
        max_research_rounds=research_cfg.get("max_rounds", 2),
        min_sources_per_task=research_cfg.get("min_sources_per_task", 2),
        max_followup_tasks=research_cfg.get("max_followup_tasks", 3),
    )

    try:
        report = await orchestrator.run(query, config=run_cfg)
    finally:
        from src.tools.web_search import WebSearchTool

        await WebSearchTool.close_session()

    logger.info(
        f"[Orchestrator] 报告生成完成 | 置信度={report.confidence:.2f} | "
        f"搜索轮数={report.num_searches} | 研究轮次={len(report.research_rounds)}"
    )
    return report


async def run_research(query: str, config: dict, modules: dict[str, Any]) -> str:
    """
    执行完整的研究流程。

    流程：
        1. Orchestrator 调用 Planner 拆解问题为子任务 DAG
        2. Orchestrator 调度 AgentPool 中的子 Agent 并行/串行执行
        3. 子 Agent 调用 Tools 检索信息并生成子报告
        4. Evidence Pipeline 归一化来源并核验 claims
        5. IterResearch 对来源不足的任务定向补搜
        6. 输出最终研究报告和结构化证据

    Args:
        query: 用户输入的研究问题。
        config: 全局配置字典。
        modules: 已初始化的模块实例字典。

    Returns:
        最终研究报告文本（Markdown 格式）。
    """
    start_time = time.time()
    report = await run_research_report(query, config, modules)

    elapsed = time.time() - start_time
    logging.getLogger("runner").info(f"研究完成，耗时: {elapsed:.2f} 秒")

    # 组装最终输出
    final_report = format_report(report, elapsed)
    return final_report


def format_report(report, elapsed: float) -> str:
    """将 ResearchReport 格式化为 Markdown 文本。"""
    content = report.content or ""

    # 统一置信度：如果正文中有 LLM 自评的"整体置信度"，替换为实际计算值，避免不一致
    content = re.sub(
        r"(整体置信度|Overall Confidence|置信度)[:：]\s*0?\.\d+",
        f"\\1: {report.confidence:.2f}",
        content,
        flags=re.I,
    )

    lines = [
        f"# 研究报告：{report.query}",
        "",
        "---",
        "",
        content,
        "",
        "---",
        "",
        "## 元信息",
        "",
        f"- **置信度**: {report.confidence:.2f}",
        f"- **搜索轮数**: {report.num_searches}",
        f"- **重规划次数**: {report.num_replan}",
        f"- **迭代研究轮数**: {len(report.research_rounds)}",
        f"- **引用蕴含率**: {report.evidence_metrics.get('citation_entailment', 0.0):.2%}",
        f"- **无证据结论率**: {report.evidence_metrics.get('unsupported_claim_rate', 0.0):.2%}",
        f"- **总耗时**: {elapsed:.2f} 秒",
        "",
    ]

    if report.sources:
        lines.append("## 参考来源")
        lines.append("")
        for i, src in enumerate(report.sources, 1):
            title = src.get("title", "未知标题")
            url = src.get("url", "")
            snippet = src.get("snippet", "")
            lines.append(f"{i}. [{title}]({url}) — {snippet}")
        lines.append("")

    return "\n".join(lines)


# Backward-compatible alias for callers created before the public formatter.
_format_report = format_report


def serialize_report(report) -> dict[str, Any]:
    """Convert a structured ResearchReport into JSON-compatible data."""
    return {
        "run_id": report.run_id,
        "query": report.query,
        "content": report.content,
        "sources": report.sources,
        "claims": report.claims,
        "confidence": report.confidence,
        "num_searches": report.num_searches,
        "num_replan": report.num_replan,
        "research_rounds": report.research_rounds,
        "evidence_metrics": report.evidence_metrics,
        "runtime_metrics": report.runtime_metrics,
    }


def save_structured_report(report, output_dir: str = "outputs/reports") -> str:
    os.makedirs(output_dir, exist_ok=True)
    run_id = report.run_id or datetime.now().strftime("techresearch-%Y%m%d-%H%M%S")
    filepath = os.path.join(output_dir, f"{run_id}.json")
    with open(filepath, "w", encoding="utf-8") as handle:
        json.dump(serialize_report(report), handle, ensure_ascii=False, indent=2)
    return filepath


# ---------------------------------------------------------------------------
# 报告保存
# ---------------------------------------------------------------------------
def save_report(report: str, query: str, output_dir: str = "outputs/reports") -> str:
    """
    将研究报告保存到文件。

    文件名格式：report_YYYYMMDD_HHMMSS_<query前20字>.md
    """
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_query = "".join(c if c.isalnum() or c in "_-" else "_" for c in query[:20])
    filename = f"report_{timestamp}_{safe_query}.md"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(report)

    return filepath
