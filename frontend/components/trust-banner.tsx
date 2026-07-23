import type { Run } from "@/lib/types";

export function TrustBanner({ run }: { run?: Run }) {
  if (!run || !run.trust?.status) return null;
  const trust = run.trust;
  return (
    <section className={`trust-banner ${trust.status}`} aria-label={`Trust assessment: ${trust.status}`}>
      <div className="trust-score"><span>{trust.score}</span><small>/100</small></div>
      <div><span className="eyebrow">Deterministic trust gate</span><h2>{label(trust.status)}</h2><p>{trust.summary}</p></div>
      <dl><div><dt>Complete</dt><dd>{trust.successful_findings}</dd></div><div><dt>Partial</dt><dd>{trust.partial_findings}</dd></div><div><dt>Failed</dt><dd>{trust.failed_findings}</dd></div><div><dt>Domains</dt><dd>{trust.independent_domains}</dd></div></dl>
      {trust.reasons?.length ? <details><summary>Why this rating?</summary><ul>{trust.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></details> : null}
    </section>
  );
}

function label(status: string) {
  if (status === "verified") return "Evidence verified";
  if (status === "qualified") return "Use with qualifications";
  return "Evidence inconclusive";
}
