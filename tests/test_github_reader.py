from __future__ import annotations

import asyncio

import pytest

from src.tools.github_reader import GitHubReaderTool, MockGitHubReaderTool


def test_parse_github_repository_variants() -> None:
    assert GitHubReaderTool.parse_repository("openai/openai-python") == ("openai", "openai-python")
    assert GitHubReaderTool.parse_repository("https://github.com/openai/openai-python.git") == (
        "openai",
        "openai-python",
    )
    with pytest.raises(ValueError):
        GitHubReaderTool.parse_repository("not-a-repository")


def test_mock_github_reader_is_deterministic() -> None:
    result = asyncio.run(MockGitHubReaderTool().execute("owner/repo"))
    assert result["full_name"] == "owner/repo"
    assert result["license"] == "MIT"
    assert "architecture" in result["readme"]
