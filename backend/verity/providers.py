from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import quote

import httpx

from .models import CompletionRequest, CompletionResponse, SearchResult, Usage


class ProviderNotConfigured(RuntimeError):
    pass


class ProviderHTTPError(RuntimeError):
    def __init__(self, status_code: int, body: str = "", retry_after: float = 0) -> None:
        super().__init__(f"provider HTTP {status_code}: {body}".strip())
        self.status_code = status_code
        self.body = body
        self.retry_after = retry_after

    @property
    def transient(self) -> bool:
        return self.status_code in {408, 429} or self.status_code >= 500


class LLMProvider(Protocol):
    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...


class SearchProvider(Protocol):
    async def search(self, query: str, max_results: int) -> list[SearchResult]: ...


async def retry_transient[T](
    operation: Callable[[], Awaitable[T]],
    max_attempts: int = 2,
) -> T:
    for attempt in range(max(1, max_attempts)):
        try:
            return await operation()
        except (httpx.TimeoutException, httpx.NetworkError, ProviderHTTPError) as error:
            transient = not isinstance(error, ProviderHTTPError) or error.transient
            if not transient or attempt + 1 >= max_attempts:
                raise
            delay = max(0.5, getattr(error, "retry_after", 0))
            await asyncio.sleep(delay)
    raise RuntimeError("retry loop exhausted")


def _retry_after_seconds(header: str | None, body: str = "") -> float:
    if header:
        try:
            return max(0, float(header)) + 2
        except ValueError:
            try:
                return max(
                    0,
                    parsedate_to_datetime(header).timestamp() - time.time(),
                )
            except (TypeError, ValueError):
                pass
    match = re.search(r"try again in\s+([0-9.]+)(ms|s|m)", body, re.IGNORECASE)
    if not match:
        return 0
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "ms":
        return value / 1000
    if unit == "m":
        value *= 60
    return value + 2


def _groq_rates(model: str) -> tuple[float, float]:
    if "llama-3.1-8b-instant" in model:
        return 0.05, 0.08
    return 0.59, 0.79


class GroqProvider:
    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        if not self.api_key:
            raise ProviderNotConfigured("Groq is not configured")
        payload: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.prompt},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        response = await self.client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
        )
        if not response.is_success:
            raise ProviderHTTPError(
                response.status_code,
                response.text[:2000],
                _retry_after_seconds(response.headers.get("retry-after"), response.text),
            )
        decoded = response.json()
        usage = decoded.get("usage", {})
        prompt_tokens = int(usage.get("prompt_tokens", 0))
        completion_tokens = int(usage.get("completion_tokens", 0))
        input_rate, output_rate = _groq_rates(self.model)
        return CompletionResponse(
            content=decoded["choices"][0]["message"]["content"],
            provider="groq",
            model=self.model,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=int(usage.get("total_tokens", prompt_tokens + completion_tokens)),
                estimated_cost_usd=(
                    prompt_tokens * input_rate + completion_tokens * output_rate
                )
                / 1_000_000,
            ),
        )


def _gemini_rates(model: str) -> tuple[float, float]:
    return {
        "gemini-3.5-flash": (2.70, 16.20),
        "gemini-3.1-flash-lite": (0.25, 1.50),
        "gemini-2.5-flash": (0.30, 2.50),
    }.get(model, (0.10, 0.40))


class GeminiProvider:
    def __init__(self, api_key: str, model: str, client: httpx.AsyncClient) -> None:
        self.api_key = api_key
        self.model = model
        self.client = client

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        if not self.api_key:
            raise ProviderNotConfigured("Gemini is not configured")
        config: dict = {
            "temperature": request.temperature,
            "maxOutputTokens": request.max_tokens,
        }
        if request.json_mode:
            config["responseMimeType"] = "application/json"
        response = await self.client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{quote(self.model)}:generateContent",
            params={"key": self.api_key},
            json={
                "systemInstruction": {"parts": [{"text": request.system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
                "generationConfig": config,
            },
        )
        if not response.is_success:
            raise ProviderHTTPError(response.status_code, response.text[:2000])
        decoded = response.json()
        content = decoded["candidates"][0]["content"]["parts"][0]["text"]
        usage = decoded.get("usageMetadata", {})
        prompt_tokens = int(usage.get("promptTokenCount", 0))
        completion_tokens = int(usage.get("candidatesTokenCount", 0))
        input_rate, output_rate = _gemini_rates(self.model)
        return CompletionResponse(
            content=content,
            provider="gemini",
            model=self.model,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=int(usage.get("totalTokenCount", prompt_tokens + completion_tokens)),
                estimated_cost_usd=(
                    prompt_tokens * input_rate + completion_tokens * output_rate
                )
                / 1_000_000,
            ),
        )


class FallbackProvider:
    def __init__(self, primary: LLMProvider, secondary: LLMProvider) -> None:
        self.primary = primary
        self.secondary = secondary

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        try:
            return await self.primary.complete(request)
        except (ProviderNotConfigured, ProviderHTTPError) as primary_error:
            if isinstance(primary_error, ProviderHTTPError) and not (
                primary_error.status_code == 429 or primary_error.status_code >= 500
            ):
                raise
            try:
                return await self.secondary.complete(request)
            except ProviderNotConfigured:
                raise primary_error from None
            except Exception as secondary_error:
                raise RuntimeError(
                    f"primary provider failed: {primary_error}; "
                    f"fallback provider failed: {secondary_error}"
                ) from secondary_error


class SearXNGProvider:
    def __init__(self, base_url: str, client: httpx.AsyncClient) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = client

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        if not self.base_url:
            raise ProviderNotConfigured("SearXNG is not configured")
        response = await self.client.get(
            f"{self.base_url}/search",
            params={
                "q": query,
                "format": "json",
                "categories": "general",
                "language": "en",
                "safesearch": "1",
            },
            headers={"Accept": "application/json", "User-Agent": "Verity/2.0"},
        )
        if not response.is_success:
            raise ProviderHTTPError(response.status_code, "SearXNG search failed")
        results: list[SearchResult] = []
        seen: set[str] = set()
        for item in response.json().get("results", []):
            url = str(item.get("url", "")).strip()
            if not url.startswith(("http://", "https://")) or url in seen:
                continue
            seen.add(url)
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=url,
                    description=str(item.get("content", "")).strip(),
                )
            )
            if len(results) >= max_results:
                break
        if not results:
            raise RuntimeError(f'SearXNG returned no usable results for "{query}"')
        return results


class BraveProvider:
    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self.api_key = api_key
        self.client = client

    async def search(self, query: str, max_results: int) -> list[SearchResult]:
        if not self.api_key:
            raise ProviderNotConfigured("Brave Search is not configured")
        response = await self.client.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
        )
        if not response.is_success:
            raise ProviderHTTPError(response.status_code, "Brave search failed")
        return [
            SearchResult(
                title=str(item.get("title", "")).strip(),
                url=str(item.get("url", "")).strip(),
                description=str(item.get("description", "")).strip(),
            )
            for item in response.json().get("web", {}).get("results", [])
        ]
