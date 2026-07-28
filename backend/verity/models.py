from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


RunStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
FindingStatus = Literal["success", "partial", "failed"]


class SubQuestion(BaseModel):
    id: str
    question: str
    search_query: str = ""
    rationale: str
    round: int


class Plan(BaseModel):
    round: int
    sub_questions: list[SubQuestion] = Field(default_factory=list)


class SourceEvidence(BaseModel):
    title: str
    url: str
    domain: str
    summary: str
    excerpt: str
    source_type: str
    quality_score: int
    fetched_at: datetime = Field(default_factory=utc_now)


class Finding(BaseModel):
    sub_question_id: str
    question: str
    status: FindingStatus
    sources: list[SourceEvidence] = Field(default_factory=list)
    error: str = ""
    duration_ms: int = 0
    round: int


class CoverageAssessment(BaseModel):
    sub_question_id: str
    assessment: Literal["sufficient", "thin", "missing"]
    reason: str


class Contradiction(BaseModel):
    claim: str
    source_urls: list[str]
    explanation: str


class CriticOutput(BaseModel):
    coverage_assessment: list[CoverageAssessment] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    decision: Literal["PROCEED", "RE_PLAN"]
    notes_for_replan: str = ""
    forced_proceed: bool = False


class TrustAssessment(BaseModel):
    status: Literal["verified", "qualified", "inconclusive"] = "inconclusive"
    score: int = 0
    summary: str = ""
    reasons: list[str] = Field(default_factory=list)
    successful_findings: int = 0
    partial_findings: int = 0
    failed_findings: int = 0
    independent_domains: int = 0
    has_contradictions: bool = False


class LLMCallMetadata(BaseModel):
    stage: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: float
    duration_ms: int


class RunMetadata(BaseModel):
    total_latency_ms: int = 0
    stage_latency_ms: dict[str, int] = Field(default_factory=dict)
    llm_calls: list[LLMCallMetadata] = Field(default_factory=list)
    total_tokens: int = 0
    llm_estimated_cost_usd: float = 0
    search_estimated_cost_usd: float = 0
    estimated_cost_usd: float = 0
    search_queries: int = 0
    replan_occurred: bool = False
    outcomes: dict[str, int] = Field(default_factory=dict)


class RunOptions(BaseModel):
    replan_enabled: bool = True


class Run(BaseModel):
    id: str
    question: str
    status: RunStatus = "queued"
    plans: list[Plan] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    critiques: list[CriticOutput] = Field(default_factory=list)
    trust: TrustAssessment = Field(default_factory=TrustAssessment)
    report: str = ""
    metadata: RunMetadata = Field(default_factory=RunMetadata)
    error: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    options: RunOptions = Field(default_factory=RunOptions)


class Event(BaseModel):
    seq: int = 0
    run_id: str
    type: str
    data: Any
    created_at: datetime = Field(default_factory=utc_now)


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0


class CompletionRequest(BaseModel):
    system_prompt: str
    prompt: str
    json_mode: bool = False
    temperature: float = 0.1
    max_tokens: int = 1000


class CompletionResponse(BaseModel):
    content: str
    provider: str
    model: str
    usage: Usage = Field(default_factory=Usage)


class SearchResult(BaseModel):
    title: str
    url: str
    description: str = ""


class Document(BaseModel):
    url: str
    title: str = ""
    text: str
