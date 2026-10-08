from evaluation.judge import parse_json_object
from src.adversarial.json_fallback import parse_json_with_fallback


def test_json_fallback_supports_fenced_and_prose_responses() -> None:
    value, strategy = parse_json_with_fallback("```json\n{\"ok\": true}\n```")
    assert value["ok"] is True
    assert strategy == "plain_or_fenced"

    value, strategy = parse_json_with_fallback("模型说明如下：结果为 {\"score\": 8}。")
    assert value["score"] == 8
    assert strategy == "balanced_object"

    assert parse_json_object("response: {\"status\": \"supported\"}")["status"] == "supported"
