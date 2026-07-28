from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError

from .extraction import Extractor
from .models import (
    CompletionRequest,
    CompletionResponse,
    CriticOutput,
    Document,
    Event,
    Finding,
    LLMCallMetadata,
    Plan,
    Run,
    SearchResult,
    SourceEvidence,
    SubQuestion,
    TrustAssessment,
    utc_now,
)
from .providers import LLMProvider, SearchProvider, retry_transient
from .store import Repository

PROMPT_DIR = Path(__file__).with_name("prompts")
REPORT_URL_PATTERN = re.compile(r"https?://[^\s)]+")


def prompt(name: str) -> str:
    return (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")


class PlannerItem(BaseModel):
    question: str
    search_query: str
    rationale: str


class PlannerResponse(BaseModel):
    sub_questions: list[PlannerItem]


class SourceSummary(BaseModel):
    url: str
    summary: str


class SourceSummaryResponse(BaseModel):
    sources: list[SourceSummary] = Field(default_factory=list)


class UsageRecorder:
    def __init__(self) -> None:
        self.llm_calls: list[LLMCallMetadata] = []
        self.search_queries = 0
        self.search_cost_usd = 0.0

    def record_llm(
        self, stage: str, response: CompletionResponse, duration_ms: int
    ) -> None:
        self.llm_calls.append(
            LLMCallMetadata(
                stage=stage,
                provider=response.provider,
                model=response.model,
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
                estimated_cost_usd=response.usage.estimated_cost_usd,
                duration_ms=duration_ms,
            )
        )

    def record_search(self, estimated_cost_usd: float) -> None:
        self.search_queries += 1
        self.search_cost_usd += estimated_cost_usd

    def apply(self, run: Run) -> None:
        run.metadata.llm_calls = list(self.llm_calls)
        run.metadata.search_queries = self.search_queries
        run.metadata.total_tokens = sum(call.total_tokens for call in self.llm_calls)
        run.metadata.llm_estimated_cost_usd = sum(
            call.estimated_cost_usd for call in self.llm_calls
        )
        run.metadata.search_estimated_cost_usd = self.search_cost_usd
        run.metadata.estimated_cost_usd = (
            run.metadata.llm_estimated_cost_usd + self.search_cost_usd
        )


async def complete(
    provider: LLMProvider,
    recorder: UsageRecorder,
    stage: str,
    request: CompletionRequest,
) -> CompletionResponse:
    started = time.perf_counter()
    response = await retry_transient(lambda: provider.complete(request), max_attempts=4)
    recorder.record_llm(stage, response, int((time.perf_counter() - started) * 1000))
    return response


def _strip_code_fence(content: str) -> str:
    value = content.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


async def structured_completion(
    model: type[BaseModel],
    provider: LLMProvider,
    recorder: UsageRecorder,
    stage: str,
    system_prompt: str,
    user_prompt: str,
    validate: Callable[[BaseModel], None],
) -> BaseModel:
    max_tokens = {"source_summarization": 900, "critiquing": 1200}.get(stage, 1000)
    request = CompletionRequest(
        system_prompt=system_prompt,
        prompt=user_prompt,
        json_mode=True,
        temperature=0.1,
        max_tokens=max_tokens,
    )
    response = await complete(provider, recorder, stage, request)
    last_error: Exception | None = None
    for attempt in range(2):
        try:
            value = model.model_validate_json(_strip_code_fence(response.content))
            validate(value)
            return value
        except (ValidationError, ValueError) as error:
            last_error = error
            if attempt:
                break
            request.prompt = (
                f"{user_prompt}\n\nYour previous response was invalid: {error}. "
                "Return corrected JSON only."
            )
            response = await complete(provider, recorder, f"{stage}_json_retry", request)
    raise ValueError(f"structured response invalid after retry: {last_error}")


class Planner:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def create(
        self,
        question: str,
        round_number: int,
        critic_notes: str,
        prior_findings: list[Finding],
        recorder: UsageRecorder,
    ) -> Plan:
        system = prompt("planner_v1")
        user = f"Original question:\n{question}"
        minimum, maximum = 3, 6
        if round_number:
            system = prompt("replanner_v1")
            minimum, maximum = 1, 3
            user = (
                f"Original question:\n{question}\n\nCritic notes:\n{critic_notes}"
                "\n\nPrior findings:\n"
                f"{json.dumps([item.model_dump(mode='json') for item in prior_findings])}"
            )

        def validate(value: BaseModel) -> None:
            assert isinstance(value, PlannerResponse)
            if not minimum <= len(value.sub_questions) <= maximum:
                raise ValueError(f"expected {minimum}-{maximum} sub-questions")
            seen: set[str] = set()
            prior = {item.question.strip().lower() for item in prior_findings}
            for item in value.sub_questions:
                normalized = item.question.strip().lower()
                if not all(
                    part.strip() for part in (item.question, item.search_query, item.rationale)
                ):
                    raise ValueError("question, search_query, and rationale are required")
                if len(item.search_query) > 180 or normalized in seen or normalized in prior:
                    raise ValueError("duplicate or invalid sub-question")
                seen.add(normalized)

        value = await structured_completion(
            PlannerResponse, self.llm, recorder, "planning", system, user, validate
        )
        assert isinstance(value, PlannerResponse)
        return Plan(
            round=round_number,
            sub_questions=[
                SubQuestion(
                    id=f"q-r{round_number}-{index}",
                    question=item.question.strip(),
                    search_query=item.search_query.strip(),
                    rationale=item.rationale.strip(),
                    round=round_number,
                )
                for index, item in enumerate(value.sub_questions, 1)
            ],
        )


class EvidenceCache:
    def __init__(self, ttl_seconds: int = 1800) -> None:
        self.ttl = ttl_seconds
        self.searches: dict[str, tuple[float, list[SearchResult]]] = {}
        self.documents: dict[str, tuple[float, Document]] = {}

    def _get(self, store: dict, key: str):
        item = store.get(key)
        if not item or item[0] < time.monotonic():
            store.pop(key, None)
            return None
        return item[1]

    def get_search(self, key: str) -> list[SearchResult] | None:
        return self._get(self.searches, key)

    def set_search(self, key: str, value: list[SearchResult]) -> None:
        self.searches[key] = (time.monotonic() + self.ttl, value)

    def get_document(self, key: str) -> Document | None:
        return self._get(self.documents, key)

    def set_document(self, key: str, value: Document) -> None:
        self.documents[key] = (time.monotonic() + self.ttl, value)


class Executor:
    def __init__(
        self,
        llm: LLMProvider,
        search: SearchProvider,
        extractor: Extractor,
        concurrency: int,
        search_cost_per_query: float,
    ) -> None:
        self.llm = llm
        self.search = search
        self.extractor = extractor
        self.semaphore = asyncio.Semaphore(max(1, concurrency))
        self.search_cost_per_query = search_cost_per_query
        self.cache = EvidenceCache()

    async def execute(
        self,
        plan: Plan,
        recorder: UsageRecorder,
        on_finding: Callable[[Finding], Awaitable[None]],
        emit: Callable[[str, object], Awaitable[None]],
    ) -> list[Finding]:
        async def execute_subquestion(sub: SubQuestion) -> Finding:
            async with self.semaphore:
                await emit("subquestion_started", sub)
                finding = await self._execute_one(sub, recorder)
                await on_finding(finding)
                await emit(
                    "subquestion_failed" if finding.status == "failed" else "subquestion_completed",
                    finding,
                )
                return finding

        return await asyncio.gather(
            *(execute_subquestion(item) for item in plan.sub_questions)
        )

    async def _execute_one(self, sub: SubQuestion, recorder: UsageRecorder) -> Finding:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(60):
                query = sub.search_query.strip() or sub.question.strip().rstrip("?")
                cache_key = f"{query}|4"
                results = self.cache.get_search(cache_key)
                if results is None:
                    recorder.record_search(self.search_cost_per_query)
                    results = await retry_transient(
                        lambda: self.search.search(query, 4), max_attempts=2
                    )
                    self.cache.set_search(cache_key, results)
                page_results = await asyncio.gather(
                    *(self._fetch_result(item) for item in results)
                )
                documents = [item[0] for item in page_results if item[0] is not None]
                titles = {
                    item[0].url: item[1]
                    for item in page_results
                    if item[0] is not None
                }
                direct_failures = sum(1 for item in page_results if item[2])
                sources = (
                    await self._summarize(sub, documents, titles, recorder)
                    if documents
                    else []
                )
                rejected = len(documents) - len(sources)
                status, error = classify_evidence_path(
                    sources,
                    len(results),
                    direct_failures,
                    rejected,
                )
        except Exception as exception:
            status, sources = "failed", []
            error = str(exception)
        return Finding(
            sub_question_id=sub.id,
            question=sub.question,
            status=status,
            sources=sources,
            error=error,
            duration_ms=int((time.perf_counter() - started) * 1000),
            round=sub.round,
        )

    async def _fetch_result(
        self, result: SearchResult
    ) -> tuple[Document | None, str, bool]:
        cached = self.cache.get_document(result.url)
        if cached:
            return cached, cached.title or result.title, False
        try:
            document = await retry_transient(
                lambda: self.extractor.fetch(result.url), max_attempts=2
            )
            if result.description.strip():
                document.text = (
                    f"Search result excerpt: {result.description.strip()}\n\n"
                    f"Fetched page content:\n{document.text}"
                )
            self.cache.set_document(result.url, document)
            return document, document.title or result.title, False
        except Exception:
            snippet = result.description.strip()
            if len(snippet) >= 60:
                return (
                    Document(
                        url=result.url,
                        title=result.title,
                        text=f"Search result excerpt: {snippet}",
                    ),
                    result.title,
                    True,
                )
            return None, result.title, True

    async def _summarize(
        self,
        sub: SubQuestion,
        documents: list[Document],
        titles: dict[str, str],
        recorder: UsageRecorder,
    ) -> list[SourceEvidence]:
        pages = "\n".join(
            f"\n--- PAGE {index} ---\nURL: {doc.url}\nTitle: {doc.title}\nText:\n{doc.text}"
            for index, doc in enumerate(documents, 1)
        )
        allowed = {doc.url for doc in documents}

        def validate(value: BaseModel) -> None:
            assert isinstance(value, SourceSummaryResponse)
            for source in value.sources:
                if source.url not in allowed or not source.summary.strip():
                    raise ValueError("summary returned an unknown URL or empty summary")

        value = await structured_completion(
            SourceSummaryResponse,
            self.llm,
            recorder,
            "source_summarization",
            prompt("source_summary_v1"),
            f"Sub-question:\n{sub.question}\n\nPages:\n{pages}",
            validate,
        )
        assert isinstance(value, SourceSummaryResponse)
        documents_by_url = {doc.url: doc for doc in documents}
        evidence: list[SourceEvidence] = []
        seen: set[str] = set()
        for source in value.sources:
            if source.url in seen:
                continue
            seen.add(source.url)
            domain = urlparse(source.url).hostname or "unknown"
            domain = domain.lower().removeprefix("www.")
            source_type, quality = classify_source(domain)
            document = documents_by_url[source.url]
            evidence.append(
                SourceEvidence(
                    title=(titles.get(source.url) or source.url).strip(),
                    url=source.url,
                    domain=domain,
                    summary=source.summary.strip(),
                    excerpt=compact_excerpt(document.text, 360),
                    source_type=source_type,
                    quality_score=quality,
                )
            )
        return evidence


def classify_source(domain: str) -> tuple[str, int]:
    if domain.endswith((".gov", ".gov.uk", ".europa.eu")):
        return "government", 95
    if domain in {"fastapi.tiangolo.com", "docs.python.org"}:
        return "documentation", 95
    if domain.startswith("docs.") or domain.endswith(".readthedocs.io"):
        return "documentation", 85
    if domain == "pypi.org":
        return "registry", 80
    research_domains = ("nature.com", "sciencedirect.com")
    if domain.endswith(".edu") or any(
        value in domain for value in research_domains
    ):
        return "research", 90
    if any(value in domain for value in ("reuters.com", "apnews.com", "bbc.")):
        return "news", 80
    if any(value in domain for value in ("wikipedia.org", "medium.com", "blog")):
        return "secondary", 55
    return "web", 65


def classify_evidence_path(
    sources: list[SourceEvidence],
    result_count: int,
    direct_failures: int,
    rejected: int,
) -> tuple[str, str]:
    if not sources:
        return (
            "failed",
            f"no usable evidence: {direct_failures} direct fetches failed; "
            f"{rejected} documents were irrelevant or unsupported",
        )
    independent_domains = {
        (source.domain or (urlparse(source.url).hostname or "")).removeprefix("www.")
        for source in sources
        if source.domain or urlparse(source.url).hostname
    }
    if len(sources) >= 2 and len(independent_domains) >= 2:
        return "success", ""
    return (
        "partial",
        f"{len(sources)} of {result_count} sources produced usable evidence across "
        f"{len(independent_domains)} independent domains; "
        f"{direct_failures} direct fetches used snippets or failed",
    )


def compact_excerpt(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    return compact if len(compact) <= limit else compact[:limit].strip() + "…"


class Critic:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def review(
        self,
        question: str,
        plans: list[Plan],
        findings: list[Finding],
        recorder: UsageRecorder,
    ) -> CriticOutput:
        expected = {sub.id for plan in plans for sub in plan.sub_questions}
        allowed_urls = {source.url for item in findings for source in item.sources}

        def validate(value: BaseModel) -> None:
            assert isinstance(value, CriticOutput)
            covered = [item.sub_question_id for item in value.coverage_assessment]
            if set(covered) != expected or len(covered) != len(set(covered)):
                raise ValueError("critic coverage does not match planned questions")
            if value.decision == "RE_PLAN" and not value.notes_for_replan.strip():
                raise ValueError("notes_for_replan required")
            for contradiction in value.contradictions:
                if len(contradiction.source_urls) < 2 or any(
                    url not in allowed_urls for url in contradiction.source_urls
                ):
                    raise ValueError("contradiction references invalid sources")

        payload = {
            "question": question,
            "plans": [item.model_dump(mode="json") for item in plans],
            "findings": [item.model_dump(mode="json") for item in findings],
        }
        value = await structured_completion(
            CriticOutput,
            self.llm,
            recorder,
            "critiquing",
            prompt("critic_v1"),
            json.dumps(payload),
            validate,
        )
        assert isinstance(value, CriticOutput)
        return value


def enforce_critic_decision(output: CriticOutput, findings: list[Finding]) -> None:
    missing_or_thin = any(
        item.assessment != "sufficient" for item in output.coverage_assessment
    )
    has_success = any(item.status == "success" for item in findings)
    has_failure = any(item.status == "failed" for item in findings)
    if output.decision == "PROCEED" and (missing_or_thin or not has_success or has_failure):
        output.decision = "RE_PLAN"
        output.notes_for_replan = (
            output.notes_for_replan
            + " Deterministic trust gate requires resolving thin, missing, failed, "
            "or entirely partial evidence before a confident answer."
        ).strip()


def assess_trust(
    findings: list[Finding], critiques: list[CriticOutput]
) -> TrustAssessment:
    if not findings:
        return TrustAssessment(
            status="inconclusive",
            score=0,
            summary="No evidence was available to assess.",
            reasons=["The run produced no research findings."],
        )

    successful = sum(item.status == "success" for item in findings)
    partial = sum(item.status == "partial" for item in findings)
    failed = sum(item.status == "failed" for item in findings)
    domains = {
        (source.domain or (urlparse(source.url).hostname or "")).removeprefix("www.")
        for item in findings
        for source in item.sources
        if source.domain or urlparse(source.url).hostname
    }
    contradictions = any(item.contradictions for item in critiques)
    forced_proceed = any(item.forced_proceed for item in critiques)
    source_scores = [
        source.quality_score for item in findings for source in item.sources
    ]
    average_quality = round(sum(source_scores) / len(source_scores)) if source_scores else 0
    total = len(findings)
    score, reasons = 100, []

    if partial:
        penalty = round(40 * partial / total)
        score -= penalty
        reasons.append(
            f"{partial} of {total} research paths had usable but incomplete evidence."
        )
    if failed:
        score -= round(50 * failed / total)
        reasons.append(f"{failed} research paths failed.")
    if not successful:
        score = min(score, 45)
        reasons.append("No research path met the full-support threshold.")
    if len(domains) < 2:
        score = min(score, 30)
        reasons.append("Fewer than two independent source domains were available.")
    if average_quality < 70:
        quality_penalty = min(15, 70 - average_quality)
        score -= quality_penalty
        reasons.append(
            f"Average retained source quality was moderate ({average_quality}/100)."
        )
    if contradictions:
        score -= 15
        reasons.append("The critic found unresolved contradictory evidence.")
    if forced_proceed:
        score -= 10
        reasons.append(
            "The run reached its re-plan limit; unresolved gaps remain reflected in the score."
        )

    score = max(0, score)
    if score < 50 or not successful or len(domains) < 2:
        status = "inconclusive"
    elif partial or failed or contradictions or forced_proceed or average_quality < 70:
        status = "qualified"
    else:
        status = "verified"
    summaries = {
        "verified": "Evidence coverage passed Verity's deterministic trust gate.",
        "qualified": "The answer is usable with material qualifications.",
        "inconclusive": "Evidence is insufficient for a confident direct answer.",
    }
    return TrustAssessment(
        status=status,
        score=score,
        summary=summaries[status],
        reasons=reasons,
        successful_findings=successful,
        partial_findings=partial,
        failed_findings=failed,
        independent_domains=len(domains),
        has_contradictions=contradictions,
    )


class Writer:
    def __init__(self, llm: LLMProvider) -> None:
        self.llm = llm

    async def write(
        self,
        question: str,
        findings: list[Finding],
        critiques: list[CriticOutput],
        trust: TrustAssessment,
        recorder: UsageRecorder,
    ) -> str:
        allowed_urls = {source.url for item in findings for source in item.sources}
        payload = json.dumps(
            {
                "question": question,
                "findings": [item.model_dump(mode="json") for item in findings],
                "critic_reviews": [item.model_dump(mode="json") for item in critiques],
                "trust_assessment": trust.model_dump(mode="json"),
            }
        )
        request = CompletionRequest(
            system_prompt=prompt("writer_v1"),
            prompt=payload,
            temperature=0.2,
            max_tokens=1800,
        )
        for attempt in range(2):
            response = await complete(
                self.llm,
                recorder,
                "writing" if not attempt else "writing_validation_retry",
                request,
            )
            report = response.content.strip()
            try:
                validate_report(report, allowed_urls)
                return report
            except ValueError as error:
                if attempt:
                    raise
                request.prompt = (
                    f"{payload}\n\nYour previous report was invalid: {error}. "
                    "Rewrite the full report and satisfy every section and citation rule."
                )
        raise ValueError("writer failed validation")


def validate_report(report: str, allowed_urls: set[str]) -> None:
    if not report:
        raise ValueError("report is empty")
    for marker in ("**Direct answer:**", "## References", "## Gaps & Caveats"):
        if marker not in report:
            raise ValueError(f"missing required report marker {marker!r}")
    if allowed_urls and "[1]" not in report:
        raise ValueError("report has evidence but no numbered inline citation")
    for raw_url in REPORT_URL_PATTERN.findall(report):
        if raw_url.rstrip(".,;:") not in allowed_urls:
            raise ValueError(f"report cites unknown URL {raw_url!r}")


class Engine:
    def __init__(
        self,
        planner: Planner,
        executor: Executor,
        critic: Critic,
        writer: Writer,
        repository: Repository,
        publish: Callable[[Event], Awaitable[None]],
    ) -> None:
        self.planner = planner
        self.executor = executor
        self.critic = critic
        self.writer = writer
        self.repository = repository
        self.publish = publish

    async def emit(self, run_id: str, event_type: str, data: object) -> None:
        if isinstance(data, BaseModel):
            data = data.model_dump(mode="json")
        event = Event(run_id=run_id, type=event_type, data=data)
        await self.repository.append_event(event)
        await self.publish(event)

    async def run(self, run: Run) -> None:
        started = time.perf_counter()
        recorder = UsageRecorder()
        run.status = "running"
        run.started_at = utc_now()
        await self.repository.save_run(run)

        async def save_finding(finding: Finding) -> None:
            run.findings.append(finding)
            await self.repository.save_run(run)

        async def fail(stage: str, error: BaseException, cancelled: bool = False) -> None:
            run.status = "cancelled" if cancelled else "failed"
            run.error = (
                "Research run cancelled."
                if cancelled
                else f"{stage}: {error}"
            )
            run.completed_at = utc_now()
            run.metadata.total_latency_ms = int((time.perf_counter() - started) * 1000)
            recorder.apply(run)
            await self.repository.save_run(run)
            await self.emit(
                run.id,
                "run_cancelled" if cancelled else "run_failed",
                {"stage": stage, "error": run.error},
            )

        async def timed(stage: str, operation: Awaitable):
            stage_started = time.perf_counter()
            try:
                return await operation
            finally:
                run.metadata.stage_latency_ms[stage] = (
                    run.metadata.stage_latency_ms.get(stage, 0)
                    + int((time.perf_counter() - stage_started) * 1000)
                )

        try:
            plan = await timed(
                "planning", self.planner.create(run.question, 0, "", [], recorder)
            )
            run.plans.append(plan)
            await self.emit(run.id, "plan_created", plan)
            await self.repository.save_run(run)

            await timed(
                "executing",
                self.executor.execute(
                    plan,
                    recorder,
                    save_finding,
                    lambda event_type, data: self.emit(run.id, event_type, data),
                ),
            )
            critique = await timed(
                "critiquing",
                self.critic.review(run.question, run.plans, run.findings, recorder),
            )
            enforce_critic_decision(critique, run.findings)
            if critique.decision == "RE_PLAN" and not run.options.replan_enabled:
                critique.forced_proceed = True
                critique.decision = "PROCEED"
                critique.notes_for_replan += (
                    " Re-plan disabled for this evaluation variant; proceeding with gaps."
                )
            run.critiques.append(critique)
            await self.emit(run.id, "critic_decision", critique)
            await self.repository.save_run(run)

            if critique.decision == "RE_PLAN":
                run.metadata.replan_occurred = True
                await self.emit(
                    run.id,
                    "replan_started",
                    {"round": 1, "notes": critique.notes_for_replan},
                )
                replan = await timed(
                    "planning",
                    self.planner.create(
                        run.question,
                        1,
                        critique.notes_for_replan,
                        run.findings,
                        recorder,
                    ),
                )
                run.plans.append(replan)
                await self.emit(run.id, "plan_created", replan)
                await timed(
                    "executing",
                    self.executor.execute(
                        replan,
                        recorder,
                        save_finding,
                        lambda event_type, data: self.emit(run.id, event_type, data),
                    ),
                )
                second = await timed(
                    "critiquing",
                    self.critic.review(run.question, run.plans, run.findings, recorder),
                )
                enforce_critic_decision(second, run.findings)
                if second.decision == "RE_PLAN":
                    second.forced_proceed = True
                    second.decision = "PROCEED"
                    second.notes_for_replan += (
                        " Maximum one re-plan cycle reached; proceeding with unresolved gaps."
                    )
                run.critiques.append(second)
                await self.emit(run.id, "critic_decision", second)
                await self.repository.save_run(run)

            run.trust = assess_trust(run.findings, run.critiques)
            await self.emit(run.id, "trust_assessed", run.trust)
            run.report = await timed(
                "writing",
                self.writer.write(
                    run.question, run.findings, run.critiques, run.trust, recorder
                ),
            )
            run.status = "completed"
            run.completed_at = utc_now()
            run.metadata.total_latency_ms = int((time.perf_counter() - started) * 1000)
            run.metadata.outcomes = {
                status: sum(item.status == status for item in run.findings)
                for status in ("success", "partial", "failed")
            }
            recorder.apply(run)
            await self.repository.save_run(run)
            await self.emit(
                run.id,
                "report_completed",
                {"report": run.report, "metadata": run.metadata.model_dump(mode="json")},
            )
        except asyncio.CancelledError as error:
            await asyncio.shield(fail("cancelled", error, cancelled=True))
            raise
        except Exception as error:
            await fail("research", error)
