# Presenting Verity

## One-line pitch

Verity is an evidence-first autonomous research system that makes agent decisions inspectable: it plans, researches in parallel, critiques evidence quality, performs one bounded corrective re-plan, and streams a cited report with explicit uncertainty.

## Resume bullets

- Built and deployed an autonomous research platform with Python, FastAPI, Next.js, SQLite, and server-sent events; also implemented an optional Supabase-ready Postgres adapter while preserving a typed end-to-end contract across asynchronous research workflows.
- Designed a planner → parallel executor → critic → writer state machine with a code-enforced one-re-plan limit and a deterministic trust gate that overrides unsupported LLM confidence.
- Implemented resilient multi-provider infrastructure across Groq/Gemini and SearXNG/Brave, including transient retry handling, bounded concurrency, partial-failure recovery, SSRF-aware extraction, and usage/cost telemetry.
- Designed optional run and event replay for a private Supabase schema with RLS and revoked browser roles; added a Vercel server proxy so backend credentials never enter the client bundle. The Supabase path is implemented but not provisioned live.
- Added reproducible evaluation tooling for HotpotQA and adversarial research prompts, plus CI covering Python lint/tests, TypeScript checks, production builds, evaluation tests, and Docker Compose validation.

Use the strongest three bullets that fit the target role. Keep the metrics honest: replace qualitative claims with measured benchmark or production numbers only after those runs exist.

## Interview narrative

1. **Problem:** LLM research answers can look confident while hiding missing evidence, contradictions, and failed searches.
2. **Architecture:** An explicit state machine persists every stage and streams append-only events, making runs replayable and debuggable.
3. **Engineering judgment:** LLM critique is advisory; deterministic code owns the re-plan limit and final trust classification.
4. **Reliability:** Independent tasks fail partially without cancelling siblings, providers have bounded retries/fallbacks, and every source retains inspectable evidence.
5. **Production:** FastAPI runs with private metasearch and SQLite persistence, Vercel serves the UI through a secret-preserving proxy, and an optional Supabase-ready Postgres path is available for future hosted durability.
6. **Next measurement:** Run the committed benchmark suite and report exact accuracy, latency, cost, abstention, and citation-integrity results.

## What I learned

- **Critique needs a contract.** Asking a model to "check its work" is too vague. Verity requires a structured assessment for every planned sub-question, distinguishes thin from missing evidence, and accepts contradictions only when they reference retained source URLs.
- **Re-planning should be corrective, not repetitive.** The second plan contains only one to three searchable questions aimed at specific gaps or contradictions. It does not restart the entire run or repeat the first plan.
- **Autonomy needs a stopping rule.** A hard one-re-plan maximum prevents open-ended loops, controls latency and cost, and forces unresolved gaps into the final report instead of hiding them behind more model calls.
- **The model should advise; code should enforce.** A deterministic gate can override an optimistic `PROCEED` decision when evidence is thin, missing, failed, or entirely partial. The final trust state is calculated from evidence outcomes, domain diversity, contradictions, source quality, and whether the run hit its re-plan limit.
- **Partial failure is useful state.** A failed search or extraction does not cancel sibling tasks. It remains visible to the critic, the timeline, the trust calculation, and the report's caveats.
- **Agent reliability is systems engineering.** Token budgets, provider fallbacks, bounded concurrency, typed state, durable event replay, SSRF-aware extraction, and observable failure events matter as much as prompt quality.
- **Evaluation must stay honest.** Verity includes a no-re-plan ablation and reproducible benchmark tooling, but unrun measurements remain `NOT RUN`. A polished demo is not benchmark evidence.

## Why this project is impressive

Verity is more than a search-and-summarize wrapper. It implements a custom, inspectable research state machine without an agent framework; makes the critique and corrective loop visible; and backs LLM judgment with deterministic safeguards. The same repository also covers the less glamorous production work that makes an agent credible: provider limits, partial failures, persistence, streaming, security boundaries, cost telemetry, and evaluation.

The standout engineering decision is the bounded re-plan loop. It demonstrates how to let an AI system revise its work without surrendering control of runtime, cost, or truthfulness. That balance between adaptive behavior and deterministic limits is what separates a compelling agent demo from a dependable software system.

## LinkedIn post

I built **Verity**, an evidence-first autonomous research agent that can recognize when its first research pass is not good enough.

Most AI research demos focus on generating an answer. I wanted to understand the harder part: **how should an agent critique its own evidence, re-plan intelligently, and know when to stop?**

Verity:

- breaks a question into independently searchable sub-questions;
- researches them concurrently and preserves partial failures;
- critiques coverage, weak evidence, and genuine contradictions;
- creates a targeted corrective plan for only the missing areas;
- allows a maximum of one re-plan cycle;
- applies a deterministic trust gate before writing a cited report with explicit gaps and caveats.

The most important lesson was that critique cannot be just another vague LLM prompt. It needs structured outputs, source validation, observable state, and code-enforced rules. Re-planning also should not mean "try everything again." It should be narrow, evidence-driven, bounded by cost and latency, and followed by a clear stopping condition.

Learning how critique and re-planning work is essential for building useful agents. Without them, an agent is mostly a linear prompt chain that can confidently continue after bad evidence. With them, it becomes a system that can detect failure, adapt its strategy, and communicate uncertainty responsibly.

Built with Python, FastAPI, Pydantic, asyncio, Next.js, SQLite, SSE, SearXNG, Groq/Gemini, Docker, reproducible evaluation tooling, and optional Supabase-ready Postgres persistence.

Repository: https://github.com/ArkaPrabhaChowdhury/verity

#AIEngineering #AgenticAI #Python #FastAPI #NextJS #LLM #MachineLearning #SoftwareEngineering

## Demo sequence

1. Start with a question containing ambiguity or conflicting evidence.
2. Show the live plan and parallel research stages.
3. Open the Evidence Ledger and inspect excerpts, domains, and partial failures.
4. Highlight the critic decision and deterministic trust override.
5. Show the single corrective re-plan and the report's explicit gaps.
6. Refresh the shared run URL to prove repository-backed event replay.

## Keywords

Python, FastAPI, Pydantic, asyncio, autonomous agents, state machines, RAG, LLM evaluation, Supabase, PostgreSQL, Next.js, React, TypeScript, SSE, Docker, CI/CD, observability, SSRF mitigation.
