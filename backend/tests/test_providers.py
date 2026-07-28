import httpx
import pytest

from verity.models import CompletionRequest, CompletionResponse
from verity.providers import (
    FallbackProvider,
    ProviderHTTPError,
    ProviderNotConfigured,
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

