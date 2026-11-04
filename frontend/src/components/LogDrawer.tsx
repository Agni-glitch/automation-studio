import { useState } from "react";
import type { ExecutionEvent, ExecutionSummary } from "../types";

function describe(e: ExecutionEvent): string {
  const p = e.payload;
  switch (e.type) {
    case "execution.started":
      return `started “${p.workflow_name}”`;
    case "execution.finished":
      return `${String(p.status).toUpperCase()} in ${Math.round(p.duration_ms)} ms${p.error ? ` — ${p.error}` : ""}`;
    case "node.succeeded":
      return `→ ${(p.outputs as string[]).join(", ")} in ${Math.round(p.duration_ms ?? 0)} ms`;
    case "node.failed":
      return `${p.error_type}: ${p.error}${p.handled ? " (handled)" : ""}`;
    case "node.skipped":
      return p.reason;
    case "node.retry":
      return `attempt ${p.attempt} failed (${p.error}); retrying in ${p.next_attempt_in_s}s`;
    case "node.log":
      return `${String(p.level).toUpperCase()}: ${p.message}`;
    default:
      return "";
  }
}

const KIND: Record<string, string> = {
  "execution.started": "info", "execution.finished": "info", "node.started": "running",
  "node.succeeded": "success", "node.failed": "failed", "node.skipped": "skipped",
  "node.cancelled": "cancelled", "node.retry": "warn", "node.log": "log",
};

function EventRows({ events, showWorkflow }: { events: ExecutionEvent[]; showWorkflow?: boolean }) {
  if (!events.length) return <div className="muted pad">Nothing yet.</div>;
  return (
    <table className="log-table">
      <tbody>
        {events.map((e, i) => (
          <tr key={i} className={`ev-${KIND[e.type] ?? "info"}`}>
            <td className="t">{new Date(e.timestamp).toLocaleTimeString()}</td>
            <td className="k">{e.type}</td>
            {showWorkflow && <td className="w">{e.execution_id.slice(0, 8)}</td>}
            <td className="n">{e.node_id ?? ""}</td>
            <td className="d">{describe(e)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

type Props = {
  open: boolean;
  onToggle: () => void;
  currentEvents: ExecutionEvent[];
  allEvents: ExecutionEvent[];
  history: ExecutionSummary[];
  running: boolean;
  onCancel: () => void;
  onOpenExecution: (id: string) => void;
  connected: boolean;
};

export default function LogDrawer(p: Props) {
  const [tab, setTab] = useState<"run" | "all" | "history">("run");
  return (
    <div className={`drawer ${p.open ? "open" : ""}`}>
      <div className="drawer-bar">
        <button className="drawer-toggle" onClick={p.onToggle}>{p.open ? "▾" : "▴"} Logs</button>
        {(["run", "all", "history"] as const).map((t) => (
          <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => { setTab(t); if (!p.open) p.onToggle(); }}>
            {t === "run" ? "This run" : t === "all" ? "All activity" : "History"}
          </button>
        ))}
        <span className="spacer" />
        {p.running && <button className="danger small" onClick={p.onCancel}>Stop run</button>}
        <span className={`conn ${p.connected ? "on" : "off"}`} title="live connection to the service">
          {p.connected ? "live" : "reconnecting…"}
        </span>
      </div>
      {p.open && (
        <div className="drawer-body">
          {tab === "run" && <EventRows events={p.currentEvents} />}
          {tab === "all" && <EventRows events={p.allEvents} showWorkflow />}
          {tab === "history" && (
            <table className="log-table clickable">
              <tbody>
                {p.history.map((x) => (
                  <tr key={x.id} onClick={() => p.onOpenExecution(x.id)} className={`ev-${x.status === "success" ? "success" : x.status === "failed" ? "failed" : "info"}`}>
                    <td className="t">{new Date(x.started_at).toLocaleString()}</td>
                    <td className="k">{x.status}</td>
                    <td className="n">{x.workflow_name}</td>
                    <td className="d">{x.error ?? ""}</td>
                  </tr>
                ))}
                {!p.history.length && <tr><td className="muted pad">No executions yet.</td></tr>}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
