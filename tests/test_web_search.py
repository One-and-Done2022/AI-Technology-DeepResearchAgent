import asyncio

from src.tools.web_search import WebSearchTool


def test_openalex_backend_is_keyless() -> None:
    tool = WebSearchTool(backend="openalex")
    assert tool.backend == "openalex"
    assert tool.openalex_endpoint


def test_openalex_response_mapping(monkeypatch) -> None:
    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            return {
                "results": [{
                    "title": "Attention Is All You Need",
                    "publication_date": "2017-06-12",
                    "abstract_inverted_index": {"Transformer": [0], "uses": [1], "attention": [2]},
                    "primary_location": {"landing_page_url": "https://arxiv.org/abs/1706.03762"},
                }]
            }

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    tool = WebSearchTool(backend="openalex")
    monkeypatch.setattr(tool, "_get_session", lambda: Session())
    result = asyncio.run(tool.execute("Transformer", top_n=1))
    assert result["source"] == "openalex"
    assert result["results"][0]["url"].endswith("1706.03762")
    assert "attention" in result["results"][0]["snippet"]


def test_openalex_quota_falls_back_to_arxiv(monkeypatch) -> None:
    class Response:
        def __init__(self, status, payload=None, text=""):
            self.status = status
            self.payload = payload or {}
            self._text = text

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def json(self):
            return self.payload

        async def text(self):
            return self._text

    xml = """<?xml version='1.0' encoding='UTF-8'?>
    <feed xmlns='http://www.w3.org/2005/Atom'>
      <entry>
        <id>http://arxiv.org/abs/1706.03762</id>
        <title>Attention Is All You Need</title>
        <summary>The Transformer is based solely on attention mechanisms.</summary>
        <published>2017-06-12T00:00:00Z</published>
      </entry>
    </feed>"""

    class Session:
        def get(self, url, *args, **kwargs):
            if "openalex" in url:
                return Response(403, {"message": "Insufficient budget"})
            return Response(200, text=xml)

    tool = WebSearchTool(backend="openalex")
    monkeypatch.setattr(tool, "_get_session", lambda: Session())
    result = asyncio.run(tool.execute("Transformer self attention", top_n=1))
    assert result["source"] == "arxiv_fallback"
    assert result["fallback_from"] == "openalex"
    assert result["results"][0]["url"].endswith("1706.03762")


def test_arxiv_fallback_does_not_inject_unrelated_transformer_results(monkeypatch) -> None:
    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def text(self):
            return """<feed xmlns='http://www.w3.org/2005/Atom'></feed>"""

    class Session:
        def get(self, *args, **kwargs):
            return Response()

    tool = WebSearchTool(backend="openalex")
    monkeypatch.setattr(tool, "_get_session", lambda: Session())
    result = asyncio.run(tool._arxiv_fallback_execute("quantum finance", top_n=2))
    assert result["results"] == []
    assert "transformer" not in result.get("search_query_used", "")


def test_arxiv_fallback_prioritizes_domain_terms_over_prompt_verbs(monkeypatch) -> None:
    class Response:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def text(self):
            return """<feed xmlns='http://www.w3.org/2005/Atom'>
              <entry><id>http://arxiv.org/abs/2305.14314</id>
              <title>QLoRA: Efficient Finetuning</title>
              <summary>QLoRA reduces memory usage.</summary>
              <published>2023-05-23T00:00:00Z</published></entry>
            </feed>"""

    class Session:
        def get(self, url, *args, **kwargs):
            return Response()

    tool = WebSearchTool(backend="openalex")
    monkeypatch.setattr(tool, "_get_session", lambda: Session())
    result = asyncio.run(
        tool._arxiv_fallback_execute(
            "Search papers comparing LoRA QLoRA and full parameter tuning", top_n=1
        )
    )
    assert result["search_query_used"].startswith("all:qlora")
    assert result["results"][0]["url"].startswith("https://arxiv.org/")
