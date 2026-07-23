"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { ComparePanel } from "@/components/compare-panel";
import { DetailsPanel } from "@/components/details-panel";
import { EvidenceTable } from "@/components/evidence-table";
import { ProgressRail } from "@/components/progress-rail";
import { ReportPanel } from "@/components/report-panel";
import { Sidebar } from "@/components/sidebar";
import { SourceInspector } from "@/components/source-inspector";
import { TimelinePanel } from "@/components/timeline-panel";
import { TrustBanner } from "@/components/trust-banner";
import { WorkspaceNav, type WorkspaceView } from "@/components/workspace-nav";
import { cancelRun, createRun, deleteRun, getRun, listRunEvents, listRuns, retryRun, streamURL } from "@/lib/api";
import type { Run, RunEvent, SourceEvidence } from "@/lib/types";

const eventTypes = ["plan_created", "subquestion_started", "subquestion_completed", "subquestion_failed", "critic_decision", "replan_started", "trust_assessed", "report_completed", "run_failed", "run_cancelled"];
const examples = ["What evidence supports and challenges the claim that AI coding tools improve software quality?", "Compare the strongest forecasts for global EV adoption through 2030.", "What caused the largest revisions to recent global renewable-energy forecasts?"];
type ResearchMode = "standard" | "fast" | "compare";

export default function Home() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [activeRun, setActiveRun] = useState<Run>();
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [question, setQuestion] = useState("");
  const [mode, setMode] = useState<ResearchMode>("standard");
  const [view, setView] = useState<WorkspaceView>("evidence");
  const [selectedSource, setSelectedSource] = useState<SourceEvidence>();
  const [lastEvent, setLastEvent] = useState<string>();
  const [error, setError] = useState<string>();
  const [submitting, setSubmitting] = useState(false);
  const streamRef = useRef<EventSource | null>(null);
  const refreshTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshRuns = useCallback(async () => { try { setRuns(await listRuns()); } catch { /* backend may still be starting */ } }, []);
  const refreshEvents = useCallback(async (runID: string) => { try { setEvents(await listRunEvents(runID)); } catch { setEvents([]); } }, []);
  const refreshActive = useCallback(async (runID: string) => { const run = await getRun(runID); setActiveRun(run); setRuns((current) => [run, ...current.filter((item) => item.id !== run.id)]); return run; }, []);

  const connect = useCallback((runID: string) => {
    streamRef.current?.close();
    const source = new EventSource(streamURL(runID));
    streamRef.current = source;
    for (const eventType of eventTypes) source.addEventListener(eventType, () => {
      setLastEvent(eventType);
      if (refreshTimer.current) clearTimeout(refreshTimer.current);
      refreshTimer.current = setTimeout(() => { refreshActive(runID).catch((reason: Error) => setError(reason.message)); refreshEvents(runID); }, 80);
      if (["report_completed", "run_failed", "run_cancelled"].includes(eventType)) { source.close(); refreshRuns(); }
    });
    source.onerror = () => { if (source.readyState !== EventSource.CLOSED) setError("Live progress disconnected. The saved run can still be reopened."); };
  }, [refreshActive, refreshEvents, refreshRuns]);

  useEffect(() => { refreshRuns().then(async () => { const id = new URLSearchParams(window.location.search).get("run"); if (id) { try { const run = await refreshActive(id); setQuestion(run.question); refreshEvents(id); if (["running", "queued"].includes(run.status)) connect(id); } catch { /* stale shared URL */ } } }); return () => { streamRef.current?.close(); if (refreshTimer.current) clearTimeout(refreshTimer.current); }; }, [connect, refreshActive, refreshEvents, refreshRuns]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const value = question.trim();
    if (value.length < 8) { setError("Enter a specific research question of at least 8 characters."); return; }
    setSubmitting(true); setError(undefined); setLastEvent(undefined);
    try {
      const runIDs = mode === "compare" ? await Promise.all([createRun(value, true), createRun(value, false)]) : [await createRun(value, mode !== "fast")];
      const run = await refreshActive(runIDs[0]); setEvents([]); setActiveURL(run.id); connect(run.id); await refreshRuns();
      if (mode === "compare") setView("compare");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start the research run."); } finally { setSubmitting(false); }
  }

  async function selectRun(run: Run) { setActiveRun(run); setQuestion(run.question); setError(undefined); setView("evidence"); setActiveURL(run.id); refreshEvents(run.id); if (["running", "queued"].includes(run.status)) connect(run.id); else streamRef.current?.close(); await refreshActive(run.id).catch((reason: Error) => setError(reason.message)); }
  function newResearch() { streamRef.current?.close(); setActiveRun(undefined); setEvents([]); setQuestion(""); setLastEvent(undefined); setError(undefined); setView("evidence"); setActiveURL(); requestAnimationFrame(() => document.querySelector<HTMLTextAreaElement>("#research-question")?.focus()); }
  async function cancelActive() { if (!activeRun) return; await cancelRun(activeRun.id); setLastEvent("run_cancelled"); setTimeout(() => refreshActive(activeRun.id), 120); }
  async function retryActive() { if (!activeRun) return; const id = await retryRun(activeRun.id); const run = await refreshActive(id); setActiveURL(id); connect(id); setQuestion(run.question); }
  async function deleteActive() { if (!activeRun || !window.confirm("Delete this run and its append-only event trace?")) return; await deleteRun(activeRun.id); newResearch(); await refreshRuns(); }

  const isActive = activeRun?.status === "running" || activeRun?.status === "queued";
  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to research workspace</a><Sidebar runs={runs} selectedID={activeRun?.id} onNew={newResearch} onSelect={selectRun} />
      <main id="main" className="workspace">
        <header className="topbar"><div><span>{activeRun ? "Active run" : "Research workspace"}</span><h1>{activeRun?.question ?? "Ask a question that needs evidence"}</h1></div>{activeRun ? <code>Run {activeRun.id.slice(0, 6)}</code> : <span className="system-status"><i /> System ready</span>}</header>
        <form className="question-form" onSubmit={submit}>
          <label htmlFor="research-question">Research question</label><div className="question-controls"><textarea id="research-question" value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="What should Verity investigate?" rows={3} maxLength={4000} disabled={submitting} /><div><button type="submit" disabled={submitting}>{submitting ? "Starting…" : mode === "compare" ? "Run comparison" : "Start research"}</button><span>Be clear and specific.</span></div></div>
          <div className="research-options"><fieldset><legend>Research mode</legend><label><input type="radio" name="mode" checked={mode === "standard"} onChange={() => setMode("standard")} /> Critic re-plan</label><label><input type="radio" name="mode" checked={mode === "fast"} onChange={() => setMode("fast")} /> No re-plan</label><label><input type="radio" name="mode" checked={mode === "compare"} onChange={() => setMode("compare")} /> Compare both modes</label></fieldset><div className="example-prompts"><span>Try an example</span>{examples.map((example, index) => <button type="button" key={example} onClick={() => setQuestion(example)}>0{index + 1}</button>)}</div></div>
          {error ? <p className="form-error" role="alert">{error}</p> : null}
        </form>
        <ProgressRail run={activeRun} lastEvent={lastEvent} /><TrustBanner run={activeRun} />
        {activeRun ? <WorkspaceNav view={view} onChange={setView} active={Boolean(isActive)} onCancel={cancelActive} onRetry={retryActive} onDelete={deleteActive} /> : null}
        {view === "evidence" ? <EvidenceTable run={activeRun} onSelectSource={setSelectedSource} /> : null}
        {view === "report" ? <ReportPanel run={activeRun} onSelectSource={setSelectedSource} /> : null}
        {view === "timeline" ? <TimelinePanel events={events} /> : null}
        {view === "compare" ? <ComparePanel active={activeRun} runs={runs} /> : null}
        {view === "details" ? <DetailsPanel run={activeRun} /> : null}
        {!activeRun && view === "evidence" ? <ReportPanel run={activeRun} /> : null}
      </main><SourceInspector source={selectedSource} onClose={() => setSelectedSource(undefined)} />
    </div>
  );
}

function setActiveURL(id?: string) { const url = new URL(window.location.href); if (id) url.searchParams.set("run", id); else url.searchParams.delete("run"); window.history.replaceState({}, "", url); }
