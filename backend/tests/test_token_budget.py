import json

import pytest

from verity.models import CompletionRequest, CompletionResponse
from verity.providers import ProviderHTTPError
from verity.token_budget import (
    TokenReducingProvider,
    estimate_request_tokens,
    reduce_completion_request,
)


def oversized_request() -> CompletionRequest:
    findings = []
    plans = []
    for index in range(9):
        sub_question_id = f"q{index}"
        plans.append(
            {
                "round": index // 6,
                "sub_questions": [
                    {
                        "id": sub_question_id,
                        "question": f"Question {index}",
                        "search_query": f"query {index}",
                        "rationale": "Important context. " * 30,
                        "round": index // 6,
                    }
                ],
            }
        )
        findings.append(
            {
                "sub_question_id": sub_question_id,
                "question": f"Question {index}",
                "status": "partial",
                "sources": [
                    {
                        "title": f"Source {source_index}",
                        "url": f"https://source{source_index}.example/{index}",
                        "domain": f"source{source_index}.example",
                        "summary": "Detailed evidence summary. " * 45,
                        "excerpt": "Long source excerpt. " * 80,
                        "source_type": "web",
                        "quality_score": 65 + source_index,
                        "fetched_at": "2026-07-28T00:00:00Z",
                    }
                    for source_index in range(4)
                ],
                "error": "Some source fetches were partial. " * 20,
                "duration_ms": 1000,
                "round": index // 6,
            }
        )
    return CompletionRequest(
        system_prompt="Critic instructions.",
        prompt=json.dumps(
            {
                "question": "Evaluate the FastAPI tradeoffs.",
                "plans": plans,
                "findings": findings,
            }
        ),
        json_mode=True,
        max_tokens=1200,
    )


def test_reducer_preserves_json_ids_and_urls_within_budget() -> None:
    request = oversized_request()
    reduced = reduce_completion_request(request, 5200)
    payload = json.loads(reduced.prompt)

    assert estimate_request_tokens(reduced) <= 5200
    assert {
        item["id"]
        for plan in payload["plans"]
        for item in plan["sub_questions"]
    } == {f"q{index}" for index in range(9)}
    assert payload["findings"][0]["sources"][0]["url"].startswith("https://")
    assert request.prompt != reduced.prompt
    assert "fetched_at" not in reduced.prompt


class RejectOnceProvider:
    def __init__(self) -> None:
        self.requests: list[CompletionRequest] = []

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.requests.append(request.model_copy(deep=True))
        if len(self.requests) == 1:
            raise ProviderHTTPError(413, "Request too large: too many tokens")
        return CompletionResponse(content="ok", provider="fake", model="fake")


async def test_layer_reduces_again_after_provider_token_rejection() -> None:
    inner = RejectOnceProvider()
    provider = TokenReducingProvider(inner, max_request_tokens=9000)

    response = await provider.complete(oversized_request())

    assert response.content == "ok"
    assert len(inner.requests) == 2
    assert estimate_request_tokens(inner.requests[1]) < estimate_request_tokens(
        inner.requests[0]
    )


async def test_layer_does_not_retry_unrelated_provider_error() -> None:
    class BrokenProvider:
        calls = 0

        async def complete(self, request: CompletionRequest) -> CompletionResponse:
            self.calls += 1
            raise ProviderHTTPError(401, "invalid key")

    inner = BrokenProvider()
    provider = TokenReducingProvider(inner)

    with pytest.raises(ProviderHTTPError):
        await provider.complete(oversized_request())
    assert inner.calls == 1
