import type { Run } from "@/lib/types";

export function TrustBanner({ run }: { run?: Run }) {
  if (!run || !run.trust?.status) return null;
  const trust = run.trust;
  return (
    <section className={`trust-banner ${trust.status}`} aria-label={`Trust assessment: ${trust.status}`}>
      <div className="trust-score"><span>{trust.score}</span><small>/100</small></div>
      <div><span className="eyebrow">Deterministic trust gate</span><h2>{label(trust.status, trust.diagnosis)}</h2><p>{trust.summary}</p><p className="trust-diagnosis">{diagnosisLabel(trust.diagnosis)}</p></div>
      <dl><div><dt>Fully supported</dt><dd>{trust.successful_findings}</dd></div><div><dt>Usable with gaps</dt><dd>{trust.partial_findings}</dd></div><div><dt>Failed</dt><dd>{trust.failed_findings}</dd></div><div><dt>Independent sources</dt><dd>{trust.independent_sources}</dd></div></dl>
      {trust.reasons?.length ? <details><summary>Why this rating?</summary><ul>{trust.reasons.map((reason) => <li key={reason}>{reason}</li>)}</ul></details> : null}
    </section>
  );
}

function label(status: string, diagnosis?: string) {
  if (status === "verified") return "Evidence verified";
  if (status === "qualified") return "Use with qualifications";
  return "Evidence inconclusive";
}

function diagnosisLabel(diagnosis?: string) {
  if (diagnosis === "retrieval_failed") return "Why: retrieval failed before enough evidence could be assessed.";
  if (diagnosis === "evidence_filtered") return "Why: candidate sources were found, but rejected by relevance or quality checks.";
  if (diagnosis === "evidence_thin") return "Why: relevant evidence was found, but coverage is still partial.";
  if (diagnosis === "source_conflict") return "Why: relevant sources disagree on a material point.";
  if (diagnosis === "not_found_after_expanded_search") return "Why: no relevant evidence was found after the expanded search completed.";
  return "";
}
