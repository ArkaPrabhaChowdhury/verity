from __future__ import annotations

import copy
import json
import math
from typing import Protocol

from .models import CompletionRequest, CompletionResponse
from .providers import ProviderHTTPError

DEFAULT_TOKEN_BUDGET = 5200
REQUEST_OVERHEAD_TOKENS = 32
MIN_PROMPT_TOKENS = 256

_PRESERVED_STRING_FIELDS = {
    "assessment",
    "decision",
    "domain",
    "id",
    "source_type",
    "status",
    "sub_question_id",
    "url",
}
_DROPPED_FIELDS = {"duration_ms", "fetched_at"}
_COMPACTION_PROFILES = (
    {
        "source_limit": 3,
        "generic_limit": 700,
        "question": 700,
        "summary": 320,
        "excerpt": 240,
        "rationale": 180,
        "error": 180,
        "reason": 180,
        "explanation": 220,
        "notes_for_replan": 240,
    },
    {
        "source_limit": 2,
        "generic_limit": 360,
        "question": 480,
        "summary": 180,
        "excerpt": 120,
        "rationale": 100,
        "error": 120,
        "reason": 120,
        "explanation": 140,
        "notes_for_replan": 160,
    },
    {
        "source_limit": 2,
        "generic_limit": 180,
        "question": 320,
        "summary": 100,
        "excerpt": 60,
        "rationale": 60,
        "error": 80,
        "reason": 80,
        "explanation": 90,
        "notes_for_replan": 100,
    },
    {
        "source_limit": 1,
        "generic_limit": 100,
        "question": 220,
        "summary": 60,
        "excerpt": 0,
        "rationale": 0,
        "error": 60,
        "reason": 60,
        "explanation": 60,
        "notes_for_replan": 70,
    },
)


class CompletionProvider(Protocol):
    async def complete(self, request: CompletionRequest) -> CompletionResponse: ...


def estimate_tokens(value: str) -> int:
    """Return a conservative tokenizer-independent estimate for English/JSON text."""
    return math.ceil(len(value.encode("utf-8")) / 3)


def estimate_request_tokens(request: CompletionRequest) -> int:
    return (
        estimate_tokens(request.system_prompt)
        + estimate_tokens(request.prompt)
        + request.max_tokens
        + REQUEST_OVERHEAD_TOKENS
    )


def _truncate(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if limit <= 0:
        return ""
    if len(compact) <= limit:
        return compact
    if limit < 20:
        return compact[:limit]
    return f"{compact[: limit - 1].rstrip()}…"


def _compact_json(value: object, profile: dict[str, int], field: str = "") -> object:
    if isinstance(value, dict):
        compacted: dict[str, object] = {}
        for key, item in value.items():
            if key in _DROPPED_FIELDS:
                continue
            compacted[key] = _compact_json(item, profile, key)
        return compacted
    if isinstance(value, list):
        items = value
        if field == "sources" and len(items) > profile["source_limit"]:
            items = sorted(
                items,
                key=lambda item: (
                    item.get("quality_score", 0) if isinstance(item, dict) else 0
                ),
                reverse=True,
            )[: profile["source_limit"]]
        return [_compact_json(item, profile) for item in items]
    if isinstance(value, str):
        if field in _PRESERVED_STRING_FIELDS:
            return value
        return _truncate(value, profile.get(field, profile["generic_limit"]))
    return value


def _json_parts(prompt: str) -> tuple[object, str] | None:
    stripped = prompt.lstrip()
    if not stripped.startswith(("{", "[")):
        return None
    try:
        value, end = json.JSONDecoder().raw_decode(stripped)
    except json.JSONDecodeError:
        return None
    return value, stripped[end:].strip()


def _reduce_prompt(prompt: str, token_budget: int) -> str:
    if estimate_tokens(prompt) <= token_budget:
        return prompt

    character_budget = max(64, token_budget * 3)
    parts = _json_parts(prompt)
    if parts:
        value, suffix = parts
        suffix = _truncate(suffix, 300)
        for profile in _COMPACTION_PROFILES:
            compacted = _compact_json(copy.deepcopy(value), profile)
            candidate = json.dumps(compacted, separators=(",", ":"), ensure_ascii=False)
            if suffix:
                candidate = f"{candidate}\n\n{suffix}"
            if estimate_tokens(candidate) <= token_budget:
                return candidate
        prompt = candidate

    if len(prompt.encode("utf-8")) <= character_budget:
        return prompt
    head_size = max(32, character_budget * 3 // 4)
    tail_size = max(16, character_budget - head_size - 30)
    return f"{prompt[:head_size].rstrip()}\n[content reduced]\n{prompt[-tail_size:].lstrip()}"


def reduce_completion_request(
    request: CompletionRequest,
    max_request_tokens: int = DEFAULT_TOKEN_BUDGET,
) -> CompletionRequest:
    prompt_budget = max(
        MIN_PROMPT_TOKENS,
        max_request_tokens
        - request.max_tokens
        - estimate_tokens(request.system_prompt)
        - REQUEST_OVERHEAD_TOKENS,
    )
    reduced = request.model_copy(deep=True)
    reduced.prompt = _reduce_prompt(reduced.prompt, prompt_budget)
    return reduced


def _is_token_limit_error(error: ProviderHTTPError) -> bool:
    body = error.body.lower()
    return error.status_code == 413 or any(
        marker in body
        for marker in (
            "request too large",
            "tokens per minute",
            "context length",
            "maximum context",
            "too many tokens",
        )
    )


class TokenReducingProvider:
    """Provider middleware that budgets requests and retries token-size rejections."""

    def __init__(
        self,
        provider: CompletionProvider,
        max_request_tokens: int = DEFAULT_TOKEN_BUDGET,
        reduction_attempts: int = 2,
    ) -> None:
        self.provider = provider
        self.max_request_tokens = max_request_tokens
        self.reduction_attempts = reduction_attempts

    async def complete(self, request: CompletionRequest) -> CompletionResponse:
        budget = self.max_request_tokens
        prepared = reduce_completion_request(request, budget)
        for attempt in range(self.reduction_attempts + 1):
            try:
                return await self.provider.complete(prepared)
            except ProviderHTTPError as error:
                if not _is_token_limit_error(error) or attempt >= self.reduction_attempts:
                    raise
                current = estimate_request_tokens(prepared)
                budget = max(
                    prepared.max_tokens + MIN_PROMPT_TOKENS,
                    min(budget, current) * 3 // 4,
                )
                prepared = reduce_completion_request(prepared, budget)
        raise RuntimeError("token reduction retry loop exhausted")
