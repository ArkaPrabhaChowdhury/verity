import type { RunEvent } from "@/lib/types";

const eventLabels: Record<string, string> = { plan_created: "Plan created", subquestion_started: "Research started", subquestion_completed: "Evidence retained", subquestion_failed: "Evidence path failed", critic_decision: "Critic decided", replan_started: "Corrective re-plan", trust_assessed: "Trust gate evaluated", report_completed: "Report completed", run_failed: "Run failed", run_cancelled: "Run cancelled" };

export function TimelinePanel({ events }: { events: RunEvent[] }) {
  return (
    <section className="panel-shell timeline-panel" aria-labelledby="timeline-title">
      <div className="panel-heading"><div><span className="eyebrow">Append-only trace</span><h2 id="timeline-title">Execution timeline</h2></div><span>{events.length} events</span></div>
      {events.length === 0 ? <p className="panel-empty">Run events will appear here.</p> : <ol>{events.map((event, index) => <li key={event.seq}><span className="event-index">{String(index + 1).padStart(2, "0")}</span><div><strong>{eventLabels[event.type] || event.type.replaceAll("_", " ")}</strong><small>{formatEventTime(event.created_at)}</small><p>{eventSummary(event)}</p></div></li>)}</ol>}
    </section>
  );
}

function formatEventTime(value: string) { return new Intl.DateTimeFormat("en", { hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(new Date(value)); }
function eventSummary(event: RunEvent) {
  if (!event.data || typeof event.data !== "object") return "State persisted.";
  const data = event.data as Record<string, unknown>;
  return String(data.question || data.notes || data.error || data.decision || "State persisted and broadcast to connected clients.");
}
