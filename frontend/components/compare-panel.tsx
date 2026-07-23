import type { Run } from "@/lib/types";

export function ComparePanel({ active, runs }: { active?: Run; runs: Run[] }) {
  const candidates = active ? runs.filter((run) => run.id !== active.id && run.question.trim().toLowerCase() === active.question.trim().toLowerCase() && run.status === "completed") : [];
  const comparison = candidates.find((run) => run.options?.replan_enabled !== active?.options?.replan_enabled) ?? candidates[0];
  return (
    <section className="panel-shell compare-panel" aria-labelledby="compare-title">
      <div className="panel-heading"><div><span className="eyebrow">Ablation view</span><h2 id="compare-title">Re-plan impact</h2></div></div>
      {!active || !comparison ? <div className="panel-empty"><strong>No matching comparison yet.</strong><p>Run the same question in “Compare both modes” to measure the critic’s marginal value.</p></div> : <div className="comparison-grid"><RunColumn title={active.options?.replan_enabled ? "Critic re-plan" : "No re-plan"} run={active} /><div className="comparison-delta"><span>Δ quality</span><strong>{signed((active.trust?.score ?? 0) - (comparison.trust?.score ?? 0))}</strong><span>Δ latency</span><strong>{signed(Math.round((active.metadata.total_latency_ms - comparison.metadata.total_latency_ms) / 1000))}s</strong><span>Δ cost</span><strong>{signedMoney(active.metadata.estimated_cost_usd - comparison.metadata.estimated_cost_usd)}</strong></div><RunColumn title={comparison.options?.replan_enabled ? "Critic re-plan" : "No re-plan"} run={comparison} /></div>}
    </section>
  );
}
function RunColumn({ title, run }: { title: string; run: Run }) { return <article><span className="mode-label">{title}</span><strong className={`trust-word ${run.trust?.status}`}>{run.trust?.status || "unrated"}</strong><dl><div><dt>Trust score</dt><dd>{run.trust?.score ?? 0}</dd></div><div><dt>Latency</dt><dd>{(run.metadata.total_latency_ms / 1000).toFixed(1)}s</dd></div><div><dt>Cost</dt><dd>${run.metadata.estimated_cost_usd.toFixed(4)}</dd></div><div><dt>Sources</dt><dd>{new Set((run.findings ?? []).flatMap((finding) => finding.sources ?? []).map((source) => source.url)).size}</dd></div></dl></article>; }
function signed(value: number) { return `${value >= 0 ? "+" : ""}${value}`; }
function signedMoney(value: number) { return `${value >= 0 ? "+" : "-"}$${Math.abs(value).toFixed(4)}`; }
