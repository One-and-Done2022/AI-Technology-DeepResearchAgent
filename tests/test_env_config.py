import os

from src.utils import env_config


def test_explicit_environment_overrides_dotenv_files(tmp_path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("SEARCH_BACKEND=env\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("SEARCH_BACKEND=local\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SEARCH_BACKEND", "openalex")
    monkeypatch.setattr(env_config, "_ENV_LOADED", False)
    assert env_config.get_env("SEARCH_BACKEND") == "openalex"
    monkeypatch.setattr(env_config, "_ENV_LOADED", False)
