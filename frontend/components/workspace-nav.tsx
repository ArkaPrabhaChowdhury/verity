export type WorkspaceView = "evidence" | "report" | "timeline" | "compare" | "details";

const views: Array<{ id: WorkspaceView; label: string }> = [
  { id: "evidence", label: "Evidence" }, { id: "report", label: "Report" }, { id: "timeline", label: "Timeline" }, { id: "compare", label: "Compare" }, { id: "details", label: "Run details" },
];

export function WorkspaceNav({ view, onChange, active, onCancel, onRetry, onDelete }: { view: WorkspaceView; onChange: (view: WorkspaceView) => void; active: boolean; onCancel: () => void; onRetry: () => void; onDelete: () => void }) {
  return (
    <div className="workspace-nav">
      <nav aria-label="Run workspace views">{views.map((item) => <button type="button" key={item.id} className={view === item.id ? "active" : ""} onClick={() => onChange(item.id)} aria-pressed={view === item.id}>{item.label}</button>)}</nav>
      <div className="run-actions">{active ? <button type="button" onClick={onCancel}>Cancel</button> : <button type="button" onClick={onRetry}>Retry</button>}<button type="button" className="danger-action" onClick={onDelete}>Delete</button></div>
    </div>
  );
}
