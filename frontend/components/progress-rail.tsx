import type { Run } from "@/lib/types";

type Phase = { name: string; state: "pending" | "active" | "complete" | "failed"; detail: string };

export function ProgressRail({ run, lastEvent }: { run?: Run; lastEvent?: string }) {
  const plans = run?.plans ?? [];
  const findings = run?.findings ?? [];
  const critiques = run?.critiques ?? [];
  const failedStage = run?.status === "failed" || run?.status === "cancelled" ? inferFailedStage(run.error) : undefined;
  const phases: Phase[] = [
    { name: "Plan", state: failedStage === "Plan" ? "failed" : plans.length ? "complete" : run?.status === "running" ? "active" : "pending", detail: failedStage === "Plan" ? "Failed" : plans.length ? "Complete" : "Pending" },
    { name: "Research", state: failedStage === "Research" ? "failed" : findings.length && critiques.length ? "complete" : plans.length ? "active" : "pending", detail: failedStage === "Research" ? "Failed" : plans.length ? `${findings.length} resolved` : "Pending" },
    { name: "Critique", state: failedStage === "Critique" ? "failed" : critiques.length && run?.report ? "complete" : critiques.length || lastEvent === "critic_decision" || lastEvent === "replan_started" ? "active" : "pending", detail: failedStage === "Critique" ? "Failed" : lastEvent === "replan_started" ? "Re-planning" : critiques.at(-1)?.decision ?? "Pending" },
    { name: "Report", state: failedStage === "Report" ? "failed" : run?.status === "completed" ? "complete" : critiques.length ? "active" : "pending", detail: failedStage === "Report" ? "Failed" : run?.status === "completed" ? "Complete" : "Pending" },
  ];

  return (
    <ol className="progress-rail" aria-label="Research progress">
      {phases.map((phase) => (
        <li key={phase.name} className={phase.state}>
          <span className="phase-marker" aria-hidden="true">{phase.state === "complete" ? "✓" : ""}</span>
          <span><strong>{phase.name}</strong><small>{phase.detail}</small></span>
        </li>
      ))}
    </ol>
  );
}

function inferFailedStage(error?: string) {
  const value = error?.toLowerCase() ?? "";
  if (value.startsWith("planning") || value.startsWith("replanning")) return "Plan";
  if (value.startsWith("critiquing") || value.startsWith("second critique")) return "Critique";
  if (value.startsWith("writing")) return "Report";
  return "Research";
}
