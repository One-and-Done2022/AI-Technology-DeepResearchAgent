from __future__ import annotations

from src.models.model_router import ModelRouter


def test_vllm_has_local_defaults_without_environment(monkeypatch) -> None:
    for key in ("VLLM_API_KEY", "VLLM_BASE_URL", "VLLM_MODEL"):
        monkeypatch.delenv(key, raising=False)
    config = ModelRouter._load_backend_config("vllm")
    assert config["base_url"] == "http://localhost:8000/v1"
    assert config["api_key"] == "EMPTY"
    assert config["model_name"] == "Qwen/Qwen2.5-7B-Instruct"
