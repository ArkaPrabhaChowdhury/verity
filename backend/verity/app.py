from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from collections import defaultdict
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .extraction import Extractor
from .models import Event, Run, RunOptions, utc_now
from .orchestrator import Critic, Engine, Executor, Planner, Writer
from .providers import (
    BraveProvider,
    CompositeSearchProvider,
    FallbackProvider,
    GeminiProvider,
    GroqProvider,
    OpenAlexProvider,
    SearXNGProvider,
)
from .store import PostgresRepository, Repository, RunNotFound, SQLiteRepository
from .token_budget import DEFAULT_TOKEN_BUDGET, TokenReducingProvider

TERMINAL_EVENTS = {"report_completed", "run_failed", "run_cancelled"}


def env(name: str, fallback: str = "") -> str:
    return os.getenv(name, "").strip() or fallback


class CreateRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=8, max_length=4000)
    replan_enabled: bool = True

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 8:
            raise ValueError("question must contain at least 8 characters")
        return value


class Broker:
    def __init__(self) -> None:
        self.subscribers: dict[str, set[asyncio.Queue[Event]]] = defaultdict(set)

    async def publish(self, event: Event) -> None:
        for queue in list(self.subscribers.get(event.run_id, set())):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass

    def subscribe(
        self,
        run_id: str,
    ) -> tuple[asyncio.Queue[Event], Callable[[], None]]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=100)
        self.subscribers[run_id].add(queue)

        def unsubscribe() -> None:
            self.subscribers[run_id].discard(queue)
            if not self.subscribers[run_id]:
                self.subscribers.pop(run_id, None)

        return queue, unsubscribe


class AppState:
    repository: Repository
    engine: Engine
    broker: Broker
    client: httpx.AsyncClient

    def __init__(self) -> None:
        self.tasks: dict[str, asyncio.Task] = {}
        self.semaphore = asyncio.Semaphore(int(env("VERITY_MAX_ACTIVE_RUNS", "2")))
        self.create_times: dict[str, list[float]] = defaultdict(list)
        self.active_runs = 0

    async def start_run(self, run: Run) -> None:
        async def execute() -> None:
            started = False
            try:
                async with self.semaphore:
                    started = True
                    self.active_runs += 1
                    await self.engine.run(run)
            except asyncio.CancelledError:
                if not started:
                    current = await self.repository.get_run(run.id)
                    if current.status == "queued":
                        current.status = "cancelled"
                        current.error = "Research run cancelled."
                        current.completed_at = utc_now()
                        await self.repository.save_run(current)
                        event = Event(
                            run_id=run.id,
                            type="run_cancelled",
                            data={"stage": "queued", "error": current.error},
                        )
                        await self.repository.append_event(event)
                        await self.broker.publish(event)
                raise
            finally:
                if started:
                    self.active_runs -= 1
                self.tasks.pop(run.id, None)

        self.tasks[run.id] = asyncio.create_task(execute(), name=f"verity-run-{run.id}")


state = AppState()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    database_url = env("VERITY_DATABASE_URL")
    state.repository = (
        PostgresRepository(database_url)
        if database_url
        else SQLiteRepository(env("VERITY_DB_PATH", "./data/verity.db"))
    )
    await state.repository.connect()
    state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(30, connect=10),
        limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
    )
    model = TokenReducingProvider(
        FallbackProvider(
            GroqProvider(
                env("GROQ_API_KEY"),
                env("GROQ_MODEL", "llama-3.1-8b-instant"),
                state.client,
            ),
            GeminiProvider(
                env("GEMINI_API_KEY"),
                env("GEMINI_MODEL", "gemini-3.5-flash"),
                state.client,
            ),
        ),
        int(env("VERITY_LLM_TOKEN_BUDGET", str(DEFAULT_TOKEN_BUDGET))),
    )
    search_name = env("VERITY_SEARCH_PROVIDER", "searxng").lower()
    if search_name == "searxng":
        search = CompositeSearchProvider(
            SearXNGProvider(env("SEARXNG_URL", "http://localhost:8888"), state.client),
            OpenAlexProvider(state.client),
        )
        default_cost = 0.0
    elif search_name == "brave":
        search = CompositeSearchProvider(
            BraveProvider(env("BRAVE_SEARCH_API_KEY"), state.client),
            OpenAlexProvider(state.client),
        )
        default_cost = 0.005
    else:
        raise RuntimeError("VERITY_SEARCH_PROVIDER must be searxng or brave")
    search_cost = float(env("VERITY_SEARCH_COST_PER_QUERY", str(default_cost)))
    state.broker = Broker()
    state.engine = Engine(
        Planner(model),
        Executor(
            model,
            search,
            Extractor(state.client, max_text=800),
            int(env("VERITY_CONCURRENCY", "1")),
            search_cost,
            int(env("VERITY_SEARCH_QUERIES_PER_QUESTION", "4")),
            int(env("VERITY_SEARCH_RESULTS_PER_QUERY", "8")),
        ),
        Critic(model),
        Writer(model),
        state.repository,
        state.broker.publish,
    )
    yield
    for task in list(state.tasks.values()):
        task.cancel()
    if state.tasks:
        await asyncio.gather(*state.tasks.values(), return_exceptions=True)
    await state.client.aclose()
    await state.repository.close()


app = FastAPI(
    title="Verity API",
    version="2.0.0",
    description="Evidence-first autonomous research with inspectable orchestration.",
    lifespan=lifespan,
)

origins = [
    item.strip()
    for item in env(
        "VERITY_ALLOWED_ORIGINS",
        "http://localhost:3000",
    ).split(",")
    if item.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


@app.middleware("http")
async def authenticate(request: Request, call_next):
    api_token = env("VERITY_API_TOKEN")
    if api_token and request.url.path != "/health":
        supplied = request.query_params.get("access_token", "")
        authorization = request.headers.get("authorization", "")
        valid = secrets.compare_digest(supplied, api_token) or secrets.compare_digest(
            authorization, f"Bearer {api_token}"
        )
        if not valid:
            return Response(
                content='{"error":"authentication required"}',
                status_code=401,
                media_type="application/json",
            )
    return await call_next(request)


@app.exception_handler(HTTPException)
async def http_error(_: Request, error: HTTPException) -> JSONResponse:
    return JSONResponse({"error": str(error.detail)}, status_code=error.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        {"error": "invalid request", "details": error.errors()},
        status_code=422,
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/status")
async def service_status() -> dict:
    return {
        "status": "ok",
        "active_runs": state.active_runs,
        "tracked_runs": len(state.tasks),
        "max_active_runs": int(env("VERITY_MAX_ACTIVE_RUNS", "2")),
        "authentication_enabled": bool(env("VERITY_API_TOKEN")),
    }


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _allow_create(request: Request) -> bool:
    key = _client_key(request)
    cutoff = time.monotonic() - 60
    recent = [created for created in state.create_times[key] if created > cutoff]
    if len(recent) >= 10:
        state.create_times[key] = recent
        return False
    state.create_times[key] = [*recent, time.monotonic()]
    return True


@app.post("/api/runs", status_code=202)
async def create_run(body: CreateRunBody, request: Request) -> dict[str, str]:
    if not _allow_create(request):
        raise HTTPException(429, "research run rate limit exceeded; retry in a minute")
    run = Run(
        id=secrets.token_hex(12),
        question=body.question,
        options=RunOptions(replan_enabled=body.replan_enabled),
    )
    await state.repository.create_run(run)
    await state.start_run(run)
    return {"run_id": run.id}


@app.get("/api/runs")
async def list_runs(limit: int = Query(20)) -> dict[str, list[Run]]:
    return {"runs": await state.repository.list_runs(limit)}


async def _get_run(run_id: str) -> Run:
    try:
        return await state.repository.get_run(run_id)
    except RunNotFound as error:
        raise HTTPException(404, "run not found") from error


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> Run:
    return await _get_run(run_id)


@app.get("/api/runs/{run_id}/events")
async def get_run_events(run_id: str) -> dict[str, list[Event]]:
    await _get_run(run_id)
    return {"events": await state.repository.list_events(run_id)}


@app.post("/api/runs/{run_id}/cancel", status_code=202)
async def cancel_run(run_id: str) -> dict[str, str]:
    run = await _get_run(run_id)
    if run.status not in {"queued", "running"}:
        raise HTTPException(409, "only queued or running research can be cancelled")
    task = state.tasks.get(run_id)
    if task:
        task.cancel()
    return {"status": "cancelling"}


@app.post("/api/runs/{run_id}/retry", status_code=202)
async def retry_run(run_id: str) -> dict[str, str]:
    original = await _get_run(run_id)
    run = Run(
        id=secrets.token_hex(12),
        question=original.question,
        options=original.options,
    )
    await state.repository.create_run(run)
    await state.start_run(run)
    return {"run_id": run.id}


@app.delete("/api/runs/{run_id}", status_code=204)
async def delete_run(run_id: str) -> Response:
    task = state.tasks.pop(run_id, None)
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    try:
        await state.repository.delete_run(run_id)
    except RunNotFound as error:
        raise HTTPException(404, "run not found") from error
    return Response(status_code=204)


def _sse(event: Event) -> str:
    return (
        f"id: {event.seq}\n"
        f"event: {event.type}\n"
        f"data: {json.dumps(event.data, separators=(',', ':'), default=str)}\n\n"
    )


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str) -> StreamingResponse:
    await _get_run(run_id)
    queue, unsubscribe = state.broker.subscribe(run_id)

    async def events() -> AsyncIterator[str]:
        last_seq = 0
        try:
            for event in await state.repository.list_events(run_id):
                yield _sse(event)
                last_seq = event.seq
                if event.type in TERMINAL_EVENTS:
                    return
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if event.seq <= last_seq:
                    continue
                yield _sse(event)
                last_seq = event.seq
                if event.type in TERMINAL_EVENTS:
                    return
        finally:
            unsubscribe()

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
