import type { Run } from "@/lib/types";

export function DetailsPanel({ run }: { run?: Run }) {
  if (!run) return <section className="panel-shell"><p className="panel-empty">Select a run to inspect its runtime details.</p></section>;
  const calls = run.metadata.llm_calls ?? [];
  return (
    <section className="panel-shell details-panel" aria-labelledby="details-title">
      <div className="panel-heading"><div><span className="eyebrow">Runtime telemetry</span><h2 id="details-title">Run details</h2></div><code>{run.id}</code></div>
      <div className="metric-grid"><Metric label="Status" value={run.status} /><Metric label="Mode" value={run.options?.replan_enabled ? "Critic re-plan" : "No re-plan"} /><Metric label="Latency" value={`${(run.metadata.total_latency_ms / 1000).toFixed(1)}s`} /><Metric label="Tokens" value={run.metadata.total_tokens.toLocaleString()} /><Metric label="Searches" value={String(run.metadata.search_queries)} /><Metric label="Candidates" value={String(run.metadata.evidence_candidates)} /><Metric label="Fetched" value={String(run.metadata.evidence_fetched)} /><Metric label="Relevant" value={String(run.metadata.evidence_relevant)} /><Metric label="Retained" value={String(run.metadata.evidence_retained)} /><Metric label="Fetch failures" value={String(run.metadata.evidence_direct_fetch_failures)} /><Metric label="Cost" value={`$${run.metadata.estimated_cost_usd.toFixed(4)}`} /></div>
      <h3>Stage latency</h3><div className="stage-bars">{Object.entries(run.metadata.stage_latency_ms ?? {}).map(([stage, ms]) => <div key={stage}><span>{stage}</span><i style={{ width: `${Math.max(4, (ms / Math.max(...Object.values(run.metadata.stage_latency_ms), 1)) * 100)}%` }} /><b>{(ms / 1000).toFixed(1)}s</b></div>)}</div>
      <h3>LLM calls</h3>{calls.length ? <div className="call-table"><div className="call-head"><span>Stage</span><span>Provider / model</span><span>Tokens</span><span>Time</span></div>{calls.map((call, index) => <div key={`${call.stage}-${index}`}><span>{call.stage}</span><span>{call.provider} · {call.model}</span><span>{call.total_tokens.toLocaleString()}</span><span>{call.duration_ms}ms</span></div>)}</div> : <p>No LLM call metadata yet.</p>}
    </section>
  );
}
function Metric({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }
