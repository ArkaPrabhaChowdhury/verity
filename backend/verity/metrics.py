from __future__ import annotations

import statistics
from collections import Counter, defaultdict


class Metrics:
    def __init__(self) -> None:
        self.counters: Counter[str] = Counter()
        self.latencies: defaultdict[str, list[float]] = defaultdict(list)

    def inc(self, name: str, value: int = 1) -> None:
        self.counters[name] += value

    def observe(self, name: str, value: float) -> None:
        self.latencies[name].append(value)

    def quantile(self, name: str, q: float) -> float:
        values = sorted(self.latencies.get(name, []))
        if not values:
            return 0.0
        return values[min(len(values) - 1, max(0, int((len(values) - 1) * q)))]

    def snapshot(self) -> dict[str, float | int]:
        return {
            "runs_total": self.counters["runs_total"],
            "runs_completed": self.counters["runs_completed"],
            "runs_failed": self.counters["runs_failed"],
            "runs_abstained": self.counters["runs_abstained"],
            "replans_total": self.counters["replans_total"],
            "fetch_failures_total": self.counters["fetch_failures_total"],
            "trust_downgrades_total": self.counters["trust_downgrades_total"],
            "queue_wait_p50_ms": self.quantile("queue_wait_ms", 0.50),
            "queue_wait_p95_ms": self.quantile("queue_wait_ms", 0.95),
            "run_latency_p50_ms": self.quantile("run_latency_ms", 0.50),
            "run_latency_p95_ms": self.quantile("run_latency_ms", 0.95),
            "avg_cost_usd": statistics.mean(self.latencies["run_cost_usd"])
            if self.latencies["run_cost_usd"]
            else 0.0,
            "evidence_retention_rate": self.counters["evidence_retained"]
            / max(1, self.counters["evidence_candidates"]),
        }

    def prometheus(self) -> str:
        lines = []
        for key, value in self.snapshot().items():
            metric = key.replace(".", "_")
            lines.append(f"verity_{metric} {value}")
        return "\n".join(lines) + "\n"


metrics = Metrics()
