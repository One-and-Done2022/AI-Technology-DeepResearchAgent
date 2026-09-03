"""GitHub repository metadata and README reader."""
from __future__ import annotations

import asyncio
import base64
import re
from typing import Any

import aiohttp

from ..utils.env_config import get_env


class GitHubReaderTool:
    name = "github_reader"
    description = (
        "Inspect a GitHub repository's metadata, README, license, activity, and latest release. "
        "Input: {'repository': 'owner/repo' or GitHub URL}."
    )

    def __init__(self, token: str | None = None, timeout: int = 20) -> None:
        self.token = token or get_env("GITHUB_TOKEN")
        self.timeout = timeout
        self.base_url = "https://api.github.com"

    @staticmethod
    def parse_repository(repository: str) -> tuple[str, str]:
        value = repository.strip().rstrip("/")
        match = re.search(r"github\.com/([^/]+)/([^/#?]+)", value, re.I)
        if match:
            return match.group(1), match.group(2).removesuffix(".git")
        parts = value.split("/")
        if len(parts) == 2 and all(parts):
            return parts[0], parts[1].removesuffix(".git")
        raise ValueError("repository must be 'owner/repo' or a GitHub repository URL")

    def get_openai_tool_schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "repository": {
                            "type": "string",
                            "description": "GitHub owner/repository or full repository URL",
                        }
                    },
                    "required": ["repository"],
                },
            },
        }

    async def execute(self, repository: str) -> dict[str, Any]:
        try:
            owner, repo = self.parse_repository(repository)
        except ValueError as exc:
            return {"error": str(exc), "repository": repository}

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "ai-technology-research-agent",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        timeout = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(headers=headers, timeout=timeout) as session:
            repo_data, readme_data, release_data = await asyncio.gather(
                self._get_json(session, f"/repos/{owner}/{repo}"),
                self._get_json(session, f"/repos/{owner}/{repo}/readme", optional=True),
                self._get_json(session, f"/repos/{owner}/{repo}/releases/latest", optional=True),
            )

        if repo_data.get("error"):
            return repo_data

        readme = ""
        encoded = readme_data.get("content", "")
        if encoded:
            try:
                readme = base64.b64decode(encoded).decode("utf-8", errors="replace")
            except (ValueError, UnicodeDecodeError):
                readme = ""

        license_data = repo_data.get("license") or {}
        return {
            "source": "github_api",
            "full_name": repo_data.get("full_name", f"{owner}/{repo}"),
            "html_url": repo_data.get("html_url", f"https://github.com/{owner}/{repo}"),
            "description": repo_data.get("description") or "",
            "readme": readme[:12000],
            "default_branch": repo_data.get("default_branch", ""),
            "language": repo_data.get("language", ""),
            "topics": repo_data.get("topics", []),
            "stars": repo_data.get("stargazers_count", 0),
            "forks": repo_data.get("forks_count", 0),
            "open_issues": repo_data.get("open_issues_count", 0),
            "license": license_data.get("spdx_id", ""),
            "created_at": repo_data.get("created_at", ""),
            "updated_at": repo_data.get("updated_at", ""),
            "pushed_at": repo_data.get("pushed_at", ""),
            "archived": bool(repo_data.get("archived", False)),
            "latest_release": {
                "tag_name": release_data.get("tag_name", ""),
                "published_at": release_data.get("published_at", ""),
                "html_url": release_data.get("html_url", ""),
            },
        }

    async def _get_json(
        self,
        session: aiohttp.ClientSession,
        path: str,
        optional: bool = False,
    ) -> dict[str, Any]:
        try:
            async with session.get(f"{self.base_url}{path}") as response:
                data = await response.json(content_type=None)
                if response.status == 200:
                    return data if isinstance(data, dict) else {}
                if optional and response.status == 404:
                    return {}
                message = data.get("message", f"HTTP {response.status}") if isinstance(data, dict) else f"HTTP {response.status}"
                return {"error": f"GitHub API error: {message}", "status": response.status}
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            if optional:
                return {}
            return {"error": f"GitHub API network error: {exc}"}


class MockGitHubReaderTool(GitHubReaderTool):
    async def execute(self, repository: str) -> dict[str, Any]:
        try:
            owner, repo = self.parse_repository(repository)
        except ValueError as exc:
            return {"error": str(exc), "repository": repository}
        await asyncio.sleep(0)
        return {
            "source": "github_mock",
            "full_name": f"{owner}/{repo}",
            "html_url": f"https://github.com/{owner}/{repo}",
            "description": "Mock repository for deterministic tests.",
            "readme": (
                f"# {repo}\n\nThis repository provides an open-source technology component "
                "with documented architecture, installation, and benchmark guidance."
            ),
            "default_branch": "main",
            "language": "Python",
            "topics": ["ai", "research"],
            "stars": 100,
            "forks": 10,
            "open_issues": 2,
            "license": "MIT",
            "created_at": "2025-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "pushed_at": "2026-01-01T00:00:00Z",
            "archived": False,
            "latest_release": {
                "tag_name": "v1.0.0",
                "published_at": "2026-01-01T00:00:00Z",
                "html_url": f"https://github.com/{owner}/{repo}/releases/tag/v1.0.0",
            },
        }
