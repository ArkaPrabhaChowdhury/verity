# Reliable execution

Verity uses Redis Streams as its production job queue.

- `verity:research` is a durable stream backed by Redis AOF (`appendfsync everysec`).
- `verity-workers` is a consumer group, so multiple backend replicas can process runs concurrently.
- A message is acknowledged only after the research task has persisted its terminal state.
- `XAUTOCLAIM` reclaims pending messages after `VERITY_REDIS_VISIBILITY_TIMEOUT_MS` (10 minutes by default), covering worker crashes and process restarts.
- Retries are bounded by `VERITY_MAX_RETRIES`; permanent failures become `dead_letter` runs and are copied to `verity:research:dead-letter` before acknowledgement.
- SQLite or Postgres remains the source of truth for run state, evidence, events, and tenant ownership. Redis contains dispatch state, not research data.

Compose starts Redis without a host port, enables AOF persistence, waits for its health check, and starts the backend only after Redis and SearXNG are healthy.
