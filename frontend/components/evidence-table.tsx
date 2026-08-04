"use client";

import { useState } from "react";
import type { Finding, Run, SourceEvidence, SubQuestion } from "@/lib/types";

export function EvidenceTable({ run, onSelectSource }: { run?: Run; onSelectSource?: (source: SourceEvidence) => void }) {
  const findings = run?.findings ?? [];
  const questions = (run?.plans ?? []).flatMap((plan) => plan.sub_questions ?? []);
  const latestCritique = (run?.critiques ?? []).at(-1);

  return (
    <section className="evidence-section" aria-labelledby="evidence-title">
      <div className="section-heading">
        <div><span className="eyebrow">Audit surface</span><h2 id="evidence-title">Evidence ledger</h2></div>
        {run?.metadata.search_queries ? <span>{run.metadata.search_queries} searches · {uniqueDomains(findings)} domains</span> : null}
      </div>
      <div className="evidence-table" role="table" aria-label="Sub-question evidence status">
        <div className="evidence-head" role="row">
          <span role="columnheader">Sub-question</span><span role="columnheader">Status</span><span role="columnheader">Time</span><span role="columnheader">Sources</span>
        </div>
        {questions.length === 0 ? <div className="evidence-empty">A research plan will appear here after you start a run.</div> : null}
        {questions.map((question) => <EvidenceRow key={question.id} question={question} finding={findings.find((item) => item.sub_question_id === question.id)} onSelectSource={onSelectSource} />)}
        {latestCritique ? (
          <div className="critic-row" role="row">
            <span aria-hidden="true">↻</span>
            <div><strong>Critic decision: {latestCritique.decision === "RE_PLAN" ? "Re-plan needed" : "Proceed"}</strong><p>{latestCritique.notes_for_replan || coverageSummary(latestCritique.coverage_assessment ?? [])}</p></div>
            <span className={`critic-state ${latestCritique.forced_proceed ? "danger" : ""}`}>{latestCritique.forced_proceed ? "Proceed with gaps" : latestCritique.decision === "RE_PLAN" ? "Re-planning" : "Reviewed"}</span>
          </div>
        ) : null}
      </div>
    </section>
  );
}

function EvidenceRow({ question, finding, onSelectSource }: { question: SubQuestion; finding?: Finding; onSelectSource?: (source: SourceEvidence) => void }) {
  const [expanded, setExpanded] = useState(false);
  const status = finding?.status ?? "running";
  const sources = finding?.sources ?? [];
  return (
    <div className={`evidence-record ${expanded ? "expanded" : ""}`} role="row">
      <div className="evidence-row">
        <button className="question-cell" type="button" onClick={() => setExpanded((value) => !value)} aria-expanded={expanded}>
          <span aria-hidden="true">{expanded ? "⌄" : "›"}</span><span>{question.question}</span>
        </button>
        <span className={`status-text ${status}`} role="cell"><i aria-hidden="true">{status === "success" ? "✓" : status === "failed" ? "!" : "◌"}</i>{status === "running" ? "Running" : capitalize(status)}</span>
        <span role="cell">{finding ? formatDuration(finding.duration_ms) : "—"}</span>
        <span role="cell">{sources.length || "—"}</span>
        {finding?.error ? <p className="row-note">{finding.error}</p> : null}
      </div>
      {expanded ? (
        <div className="evidence-drawer">
          <div className="plan-context"><span><b>Search query</b>{question.search_query || question.question}</span><span><b>Why it matters</b>{question.rationale}</span></div>
          {sources.length ? <div className="source-card-grid">{sources.map((source) => <SourceCard key={source.url} source={source} onSelect={onSelectSource} />)}</div> : <p className="drawer-empty">No usable source evidence was retained for this path.</p>}
        </div>
      ) : null}
    </div>
  );
}

function SourceCard({ source, onSelect }: { source: SourceEvidence; onSelect?: (source: SourceEvidence) => void }) {
  return (
    <article className="source-card">
      <div className="source-card-meta"><span>{source.source_type || "web"}</span><span>{source.quality_score ?? 0}/100</span></div>
      <h3>{source.title}</h3><p>{source.summary}</p>
      {source.excerpt ? <blockquote>{source.excerpt}</blockquote> : null}
      <div className="source-card-actions"><a href={source.url} target="_blank" rel="noreferrer">Open source ↗</a>{onSelect ? <button type="button" onClick={() => onSelect(source)}>Inspect</button> : null}</div>
    </article>
  );
}

function uniqueDomains(findings: Finding[]) {
  return new Set(findings.flatMap((finding) => finding.sources ?? []).map((source) => source.domain || new URL(source.url).hostname).filter(Boolean)).size;
}
function capitalize(value: string) { return value.charAt(0).toUpperCase() + value.slice(1); }
function formatDuration(ms: number) { return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`; }
function coverageSummary(items: Array<{ assessment: string }>) { const gaps = items.filter((item) => item.assessment !== "sufficient").length; return gaps ? `${gaps} evidence gap${gaps === 1 ? "" : "s"} remain.` : "Evidence coverage is sufficient to write the report."; }
