import httpx
import pytest

from verity.models import CompletionRequest, CompletionResponse
from verity.providers import (
    CrossrefProvider,
    FallbackProvider,
    OpenAlexProvider,
    ProviderHTTPError,
    ProviderNotConfigured,
    PubMedProvider,
    SearXNGProvider,
)


class FakeProvider:
    def __init__(self, result):
        self.result = result

    async def complete(self, _request):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


async def test_fallback_preserves_primary_when_secondary_is_unconfigured() -> None:
    primary_error = ProviderHTTPError(429, "rate limited")
    provider = FallbackProvider(
        FakeProvider(primary_error), FakeProvider(ProviderNotConfigured())
    )
    with pytest.raises(ProviderHTTPError) as caught:
        await provider.complete(CompletionRequest(system_prompt="", prompt="test"))
    assert caught.value is primary_error


async def test_fallback_uses_secondary() -> None:
    expected = CompletionResponse(content="ok", provider="secondary", model="test")
    provider = FallbackProvider(
        FakeProvider(ProviderNotConfigured()), FakeProvider(expected)
    )
    assert (
        await provider.complete(CompletionRequest(system_prompt="", prompt="test"))
    ) == expected


async def test_searxng_filters_duplicates_and_invalid_urls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["format"] == "json"
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "One", "url": "https://example.com/a", "content": "A"},
                    {"title": "Duplicate", "url": "https://example.com/a", "content": "B"},
                    {"title": "Invalid", "url": "ftp://example.com/b", "content": "C"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await SearXNGProvider("https://search.example", client).search("q", 5)
    assert len(results) == 1
    assert results[0].title == "One"


async def test_openalex_maps_scholarly_work_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["filter"] == "has_abstract:true"
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "title": "A research paper",
                        "doi": "https://doi.org/10.1234/example",
                        "primary_location": {"landing_page_url": "https://doi.org/10.1234/example"},
                        "abstract_inverted_index": {"Evidence": [0], "supports": [1]},
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await OpenAlexProvider(client).search("research query", 3)
    assert results[0].url == "https://doi.org/10.1234/example"
    assert results[0].description == "Evidence supports"


async def test_pubmed_maps_indexed_records() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, json={"esearchresult": {"idlist": ["123"]}})
        return httpx.Response(
            200,
            json={"result": {"123": {"uid": "123", "title": "Intermittent fasting review"}}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await PubMedProvider(client).search("intermittent fasting", 3)
    assert results[0].url == "https://pubmed.ncbi.nlm.nih.gov/123/"
    assert results[0].title == "Intermittent fasting review"


async def test_crossref_maps_doi_records() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {
                    "items": [
                        {"DOI": "10.1234/example", "title": ["Urban heat review"]}
                    ]
                }
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        results = await CrossrefProvider(client).search("urban tree heat", 3)
    assert results[0].url == "https://doi.org/10.1234/example"
    assert results[0].title == "Urban heat review"
