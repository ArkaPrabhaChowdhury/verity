"use client";

import ReactMarkdown from "react-markdown";
import type { Run, SourceEvidence } from "@/lib/types";

export function ReportPanel({ run, onSelectSource }: { run?: Run; onSelectSource?: (source: SourceEvidence) => void }) {
  const sources = orderSources(uniqueSources((run?.findings ?? []).flatMap((finding) => finding.sources ?? [])), run?.report ?? "");
  const report = linkCitations(run?.report ?? "");
  return (
    <section className="report-shell" aria-labelledby="report-title">
      <div className="report-toolbar">
        <div><span className="eyebrow">Cited synthesis</span><h2 id="report-title">Report{run?.status === "running" ? " (draft)" : ""}</h2></div>
        <div className="report-tools">{run?.report ? <><button type="button" onClick={() => navigator.clipboard.writeText(run.report)}>Copy</button><button type="button" onClick={() => download(`${run.id}.md`, run.report, "text/markdown")}>Markdown</button><button type="button" onClick={() => download(`${run.id}.json`, JSON.stringify(run, null, 2), "application/json")}>JSON</button><button type="button" onClick={() => window.print()}>PDF / Print</button></> : null}{run?.metadata.total_latency_ms ? <span>{(run.metadata.total_latency_ms / 1000).toFixed(1)}s · {run.metadata.total_tokens.toLocaleString()} tokens · ${run.metadata.estimated_cost_usd.toFixed(4)}</span> : null}</div>
      </div>
      <div className="report-layout">
        <article className="report-content">
          {report ? <ReactMarkdown components={{ h2: ({ children }) => <h2 className={String(children) === "Gaps & Caveats" ? "gaps-heading" : undefined}>{children}</h2>, a: ({ href, children }) => href?.startsWith("#source-") ? <a href={href} className="citation-link">{children}</a> : <a href={href} target="_blank" rel="noreferrer">{children}</a> }}>{report}</ReactMarkdown> : <ReportEmpty active={run?.status === "running" || run?.status === "queued"} />}
          {run?.error ? <div className="run-error" role="alert"><strong>{run.status === "cancelled" ? "Run cancelled" : "Run failed"}</strong><p>{run.error}</p></div> : null}
        </article>
        <aside className="source-rail" aria-label="Sources">
          <h3>Sources ({sources.length})</h3><p className="rail-intro">Select a citation to inspect its retained evidence.</p>
          {sources.length === 0 ? <p>Verified source links will appear as evidence resolves.</p> : null}
          <ol>{sources.map((source, index) => <li id={`source-${index + 1}`} key={source.url}><button type="button" onClick={() => onSelectSource?.(source)}><span>{source.title}</span><small>{source.domain || new URL(source.url).hostname} · {source.quality_score ?? 0}/100</small></button></li>)}</ol>
        </aside>
      </div>
    </section>
  );
}

function ReportEmpty({ active }: { active: boolean }) { return <div className={`report-empty ${active ? "active" : ""}`}><strong>{active ? "Report synthesis is waiting on evidence." : "No report yet."}</strong><p>{active ? "The writer runs after the critic is satisfied or the single re-plan limit is reached." : "Start a research run to produce a cited answer and an explicit gaps assessment."}</p></div>; }
function uniqueSources(sources: SourceEvidence[]) { const seen = new Set<string>(); return sources.filter((source) => { if (seen.has(source.url)) return false; seen.add(source.url); return true; }); }
function orderSources(sources: SourceEvidence[], report: string) { const references = report.split(/## References/i)[1] ?? ""; return sources.toSorted((left, right) => rankReference(references, left.url) - rankReference(references, right.url)); }
function rankReference(references: string, url: string) { const index = references.indexOf(url); return index < 0 ? Number.MAX_SAFE_INTEGER : index; }
function linkCitations(report: string) { return report.replace(/\[(\d+)\](?!\()/g, "[[$1]](#source-$1)"); }
function download(name: string, content: string, type: string) { const blob = new Blob([content], { type }); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = name; anchor.click(); URL.revokeObjectURL(url); }
