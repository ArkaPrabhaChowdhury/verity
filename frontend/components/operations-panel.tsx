"use client";

import { useEffect, useState } from "react";
import { getTelemetry } from "@/lib/api";
import type { Run, Telemetry } from "@/lib/types";

const cards: Array<[string, string, string]> = [
  ["Queue wait", "queue_wait_p95_ms", "ms p95"],
  ["Run latency", "run_latency_p95_ms", "ms p95"],
  ["Evidence retained", "evidence_retention_rate", "%"],
  ["Avg run cost", "avg_cost_usd", "USD"],
  ["Re-plans", "replans_total", "total"],
  ["Trust downgrades", "trust_downgrades_total", "total"],
];

function value(key: string, telemetry: Telemetry) {
  const raw = telemetry[key] ?? 0;
  if (key === "evidence_retention_rate") return `${Math.round(raw * 100)}%`;
  if (key === "avg_cost_usd") return `$${raw.toFixed(4)}`;
  return Math.round(raw).toLocaleString();
}

export function OperationsPanel({ run }: { run?: Run }) {
  const [telemetry, setTelemetry] = useState<Telemetry>({});
  useEffect(() => { getTelemetry().then(setTelemetry).catch(() => setTelemetry({})); }, [run?.status]);
  return <section className="panel-shell operations-panel" aria-labelledby="operations-title">
    <div className="panel-heading"><div><span className="eyebrow">Production control room</span><h2 id="operations-title">Telemetry &amp; reliability</h2></div><span>OpenTelemetry-ready signals</span></div>
    <div className="ops-summary"><strong>{telemetry.runs_completed ?? 0}</strong><span>completed runs observed</span><i /><strong>{telemetry.runs_failed ?? 0}</strong><span>failed runs observed</span></div>
    <div className="ops-grid">{cards.map(([label, key, suffix]) => <div key={key}><span>{label}</span><strong>{value(key, telemetry)}</strong><small>{suffix}</small></div>)}</div>
    <div className="ops-flow"><div><b>Planner</b><span>trace span</span></div><div><b>Search / fetch</b><span>failure rate tracked</span></div><div><b>Critic</b><span>re-plan decisions</span></div><div><b>Writer</b><span>trust-gated output</span></div></div>
    {run?.status === "dead_letter" ? <p className="ops-alert">This run is in the dead-letter queue after exhausting retries. Inspect the saved trace before replaying it.</p> : <p className="ops-note">Prometheus is available at <code>/metrics</code>. Run-level telemetry includes latency, tokens, cost, fetch failures, retention, and trust outcome.</p>}
  </section>;
}
