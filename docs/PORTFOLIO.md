# Presenting Verity

## One-line pitch

Verity is an evidence-first autonomous research system that makes agent decisions inspectable: it plans, researches in parallel, critiques evidence quality, performs one bounded corrective re-plan, and streams a cited report with explicit uncertainty.

## Resume bullets

- Built and deployed an autonomous research platform with Python, FastAPI, Next.js, Supabase Postgres, and server-sent events, preserving a typed end-to-end contract across asynchronous research workflows.
- Designed a planner → parallel executor → critic → writer state machine with a code-enforced one-re-plan limit and a deterministic trust gate that overrides unsupported LLM confidence.
- Implemented resilient multi-provider infrastructure across Groq/Gemini and SearXNG/Brave, including transient retry handling, bounded concurrency, partial-failure recovery, SSRF-aware extraction, and usage/cost telemetry.
- Secured durable run and event replay in a private Supabase schema with RLS and revoked browser roles; added a Vercel server proxy so backend credentials never enter the client bundle.
- Added reproducible evaluation tooling for HotpotQA and adversarial research prompts, plus CI covering Python lint/tests, TypeScript checks, production builds, evaluation tests, and Docker Compose validation.

Use the strongest three bullets that fit the target role. Keep the metrics honest: replace qualitative claims with measured benchmark or production numbers only after those runs exist.

## Interview narrative

1. **Problem:** LLM research answers can look confident while hiding missing evidence, contradictions, and failed searches.
2. **Architecture:** An explicit state machine persists every stage and streams append-only events, making runs replayable and debuggable.
3. **Engineering judgment:** LLM critique is advisory; deterministic code owns the re-plan limit and final trust classification.
4. **Reliability:** Independent tasks fail partially without cancelling siblings, providers have bounded retries/fallbacks, and every source retains inspectable evidence.
5. **Production:** FastAPI runs with private metasearch, Supabase stores durable state, and Vercel serves the UI through a secret-preserving proxy.
6. **Next measurement:** Run the committed benchmark suite and report exact accuracy, latency, cost, abstention, and citation-integrity results.

## Demo sequence

1. Start with a question containing ambiguity or conflicting evidence.
2. Show the live plan and parallel research stages.
3. Open the Evidence Ledger and inspect excerpts, domains, and partial failures.
4. Highlight the critic decision and deterministic trust override.
5. Show the single corrective re-plan and the report's explicit gaps.
6. Refresh the shared run URL to prove Supabase-backed replay.

## Keywords

Python, FastAPI, Pydantic, asyncio, autonomous agents, state machines, RAG, LLM evaluation, Supabase, PostgreSQL, Next.js, React, TypeScript, SSE, Docker, CI/CD, observability, SSRF mitigation.
