# Verity observability

The API exposes `/metrics` in Prometheus text format and `/api/telemetry` for the UI. Import `grafana-dashboard.json` into Grafana and point the panels at a Prometheus scrape of the API.

Run-level events retain the stage boundary needed for OpenTelemetry export: planner, search, fetch, critic, and writer. The current local deployment keeps the dependency-free metrics path enabled; a collector can map these counters and stage timings to OTLP without changing the research contract.

Signals include queue wait p50/p95, run latency p50/p95, estimated token cost, fetch failures, evidence retention, re-plan frequency, and trust-gate downgrade/abstention outcomes.
