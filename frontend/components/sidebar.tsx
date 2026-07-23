import type { Run } from "@/lib/types";

type SidebarProps = {
  runs: Run[];
  selectedID?: string;
  onNew: () => void;
  onSelect: (run: Run) => void;
};

const statusSymbol: Record<Run["status"], string> = {
  queued: "○",
  running: "◌",
  completed: "✓",
  failed: "!",
  cancelled: "×",
};

export function Sidebar({ runs, selectedID, onNew, onSelect }: SidebarProps) {
  return (
    <aside className="sidebar" aria-label="Research runs">
      <div className="brand-row">
        <span className="wordmark">Verity</span>
        <span className="brand-mark" aria-hidden="true">V</span>
      </div>
      <button className="new-run" type="button" onClick={onNew}>
        <span aria-hidden="true">＋</span> New research
      </button>
      <h2>Recent runs</h2>
      <nav className="run-list" aria-label="Recent runs">
        {runs.length === 0 ? <p className="empty-history">Completed and active runs will appear here.</p> : null}
        {runs.map((run) => (
          <button
            className={`run-item ${selectedID === run.id ? "selected" : ""}`}
            type="button"
            key={run.id}
            onClick={() => onSelect(run)}
            aria-current={selectedID === run.id ? "page" : undefined}
          >
            <span className="run-question">{run.question}</span>
            <span className="run-meta">
              {formatRelative(run.created_at)} · {run.id.slice(0, 6)}
            </span>
            <span className={`run-status ${run.status}`} aria-label={run.status}>{statusSymbol[run.status]}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span className="avatar" aria-hidden="true">V</span>
        <span>Local workspace</span>
      </div>
    </aside>
  );
}

function formatRelative(value: string) {
  const elapsed = Date.now() - new Date(value).getTime();
  if (elapsed < 60_000) return "Just now";
  if (elapsed < 3_600_000) return `${Math.floor(elapsed / 60_000)}m ago`;
  if (elapsed < 86_400_000) return `${Math.floor(elapsed / 3_600_000)}h ago`;
  return new Intl.DateTimeFormat("en", { month: "short", day: "numeric" }).format(new Date(value));
}
