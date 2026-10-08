from evaluation.benchmarks.hotpotqa import HotpotQABenchmark
from evaluation.benchmarks.research_bench import ResearchBench


def test_research_bench_has_35_questions_and_11_domains() -> None:
    benchmark = ResearchBench()
    assert len(benchmark.questions) == 35
    assert len({item["domain"] for item in benchmark.questions}) == 11
    result = benchmark.evaluate_report(
        "Transformer 使用注意力机制，并比较了 RNN 和 CNN。",
        "rb_001",
    )
    assert result["metrics"]["fact_accuracy"] == 1.0
    assert 0 <= result["composite_score"] <= 10


def test_hotpotqa_mock_metrics() -> None:
    benchmark = HotpotQABenchmark(use_mock=True)
    assert len(benchmark.get_questions(n=5)) == 5
    assert benchmark.get_question("hotpot_002")["answer"] == "Paris"
    result = benchmark.evaluate({"answer": "Paris"}, "hotpot_002")
    assert result["exact_match"] == 1.0
    assert result["f1"] == 1.0
    assert result["pass_at_1"] == 1.0
