"""Compatibility benchmark for the original 35-question ResearchBench.

The dataset is intentionally stored as transparent Python records so the
legacy benchmark remains runnable without downloading a hidden artifact.
It is a development/compatibility benchmark, not a claim of public benchmark
ownership.
"""
from __future__ import annotations

from typing import Any

from evaluation.metrics.claim_metrics import ClaimMetrics


def _case(case_id: str, domain: str, query: str, topics: list[str], claims: list[str]) -> dict[str, Any]:
    return {
        "id": case_id,
        "domain": domain,
        "query": query,
        "expected_topics": topics,
        "ground_truth": {f"fact_{index + 1}": claim for index, claim in enumerate(claims)},
        "required_claims": claims,
        "answerable": True,
    }


def _build_questions() -> list[dict[str, Any]]:
    groups = [
        ("technology", [
            ("比较 Transformer、RNN 和 CNN 的序列建模特点", ["Transformer", "RNN", "CNN"], ["Transformer 使用注意力机制"]),
            ("分析 Qwen2.5 与 GPT-4o 的能力和部署差异", ["Qwen2.5", "GPT-4o", "部署"], ["Qwen2.5 与 GPT-4o 的部署约束不同"]),
            ("解释向量数据库的索引和召回流程", ["向量数据库", "索引", "召回"], ["向量数据库通过相似度索引提升召回效率"]),
            ("比较 REST、gRPC 和 GraphQL 的服务调用方式", ["REST", "gRPC", "GraphQL"], ["三种接口风格在调用模型和约束上不同"]),
            ("分析 GPU 推理中的 KV Cache 优化方法", ["GPU", "KV Cache", "推理"], ["KV Cache 会影响长上下文推理的显存开销"]),
        ]),
        ("medical", [
            ("总结电子病历中的隐私保护技术", ["电子病历", "隐私", "脱敏"], ["电子病历需要脱敏和访问控制"]),
            ("比较医学影像分类中的 CNN 与 Vision Transformer", ["医学影像", "CNN", "Vision Transformer"], ["医学影像模型需要考虑数据规模和可解释性"]),
            ("分析临床研究中数据偏差的来源", ["临床研究", "数据偏差", "样本"], ["样本选择会影响临床研究结论"]),
        ]),
        ("finance", [
            ("解释金融风控中的异常检测方法", ["金融", "风控", "异常检测"], ["异常检测可以识别潜在风险交易"]),
            ("比较金融时间序列中的 ARIMA 与 Transformer", ["ARIMA", "Transformer", "时间序列"], ["时间序列模型需要处理趋势和季节性"]),
            ("分析量化交易模型的回测风险", ["量化交易", "回测", "风险"], ["回测结果可能受到未来信息泄漏影响"]),
        ]),
        ("education", [
            ("分析生成式 AI 对个性化学习的影响", ["生成式 AI", "个性化学习", "教育"], ["生成式 AI 可以辅助个性化学习反馈"]),
            ("比较在线课程和传统课堂的评价方式", ["在线课程", "传统课堂", "评价"], ["在线课程更容易记录学习过程数据"]),
            ("讨论教育数据中的公平性问题", ["教育数据", "公平性", "偏差"], ["教育数据系统需要评估不同群体的偏差"]),
        ]),
        ("legal", [
            ("分析大模型生成内容的版权风险", ["大模型", "版权", "生成内容"], ["生成内容的版权责任需要结合使用场景判断"]),
            ("比较开源许可证中的 MIT、Apache-2.0 和 GPL", ["MIT", "Apache-2.0", "GPL"], ["开源许可证对再分发和修改义务不同"]),
            ("总结软件供应链中的合规审计要点", ["软件供应链", "合规", "审计"], ["软件供应链需要追踪依赖和许可证"]),
        ]),
        ("energy", [
            ("比较光伏和风电的预测建模方法", ["光伏", "风电", "预测"], ["可再生能源预测受到天气变量影响"]),
            ("分析储能系统中的电池管理策略", ["储能", "电池", "管理"], ["电池管理系统需要估计荷电状态"]),
            ("讨论数据中心能耗优化技术", ["数据中心", "能耗", "优化"], ["数据中心能耗优化需要联合考虑计算和制冷"]),
        ]),
        ("automotive", [
            ("比较自动驾驶中的感知和规划模块", ["自动驾驶", "感知", "规划"], ["自动驾驶系统需要将感知结果传给规划模块"]),
            ("分析车载边缘计算的延迟约束", ["车载", "边缘计算", "延迟"], ["车载系统对实时延迟和可靠性有严格要求"]),
            ("总结智能座舱中的多模态交互技术", ["智能座舱", "多模态", "交互"], ["多模态交互融合语音和视觉信号"]),
        ]),
        ("gaming", [
            ("分析游戏推荐系统的冷启动问题", ["游戏", "推荐", "冷启动"], ["冷启动场景缺少用户历史行为数据"]),
            ("比较游戏服务器中的状态同步策略", ["游戏服务器", "状态同步", "网络"], ["状态同步策略需要平衡一致性和延迟"]),
            ("讨论生成式 AI 在游戏内容制作中的应用", ["生成式 AI", "游戏内容", "制作"], ["生成式 AI 可以辅助生成游戏素材和剧情草稿"]),
        ]),
        ("science", [
            ("总结科研文献检索中的语义搜索方法", ["科研", "文献检索", "语义搜索"], ["语义搜索可以利用论文内容而不只依赖关键词"]),
            ("比较科学计算中的 CPU、GPU 和 TPU", ["CPU", "GPU", "TPU"], ["不同加速器适合不同科学计算工作负载"]),
            ("分析科学数据的可重复性和版本管理", ["科学数据", "可重复性", "版本管理"], ["数据版本和实验环境会影响结果复现"]),
        ]),
        ("environment", [
            ("分析空气质量预测中的数据来源", ["空气质量", "预测", "数据"], ["空气质量预测需要结合气象和污染物数据"]),
            ("比较环境监测中的传感器网络和卫星遥感", ["环境监测", "传感器", "卫星遥感"], ["传感器和遥感在空间分辨率上具有互补性"]),
            ("讨论碳排放核算中的数据可信度", ["碳排放", "核算", "可信度"], ["碳排放核算依赖活动数据和排放因子"]),
        ]),
        ("public_policy", [
            ("分析公共部门采用生成式 AI 的治理要求", ["公共部门", "生成式 AI", "治理"], ["公共部门需要建立生成式 AI 使用规范"]),
            ("比较数字身份系统中的隐私和可用性", ["数字身份", "隐私", "可用性"], ["数字身份系统需要平衡隐私和服务可用性"]),
            ("讨论开放数据政策对 AI 创新的影响", ["开放数据", "AI 创新", "政策"], ["开放数据政策可能降低研究和开发的数据获取成本"]),
        ]),
    ]
    questions: list[dict[str, Any]] = []
    counter = 1
    for domain, entries in groups:
        for query, topics, claims in entries:
            questions.append(_case(f"rb_{counter:03d}", domain, query, topics, claims))
            counter += 1
    return questions


class ResearchBench:
    DEFAULT_QUESTIONS = _build_questions()

    def __init__(self, questions: list[dict[str, Any]] | None = None) -> None:
        self.questions = list(questions or self.DEFAULT_QUESTIONS)
        self._by_id = {question["id"]: question for question in self.questions}

    def get_questions(self, domain: str | None = None, n: int | None = None) -> list[dict[str, Any]]:
        questions = [q for q in self.questions if domain is None or q.get("domain") == domain]
        return questions[:n] if n is not None else questions

    def get_question(self, question_id: str) -> dict[str, Any]:
        if question_id not in self._by_id:
            raise ValueError(f"Unknown ResearchBench question: {question_id}")
        return self._by_id[question_id]

    def evaluate_report(self, report: Any, question_id: str) -> dict[str, Any]:
        question = self.get_question(question_id)
        if isinstance(report, dict):
            content = report.get("content", "")
        elif isinstance(report, str):
            content = report
        else:
            content = getattr(report, "content", "")
        metrics = {
            "fact_accuracy": ClaimMetrics.reference_claim_recall(
                content, list(question.get("required_claims", []))
            ),
            "comprehensiveness": ClaimMetrics.topic_coverage(
                content, list(question.get("expected_topics", []))
            ),
        }
        metrics["composite_score"] = round(
            10.0 * (0.6 * metrics["fact_accuracy"] + 0.4 * metrics["comprehensiveness"]), 4
        )
        return {
            "question_id": question_id,
            "domain": question["domain"],
            "metrics": metrics,
            "composite_score": metrics["composite_score"],
        }

