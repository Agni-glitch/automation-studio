import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  useEdgesState,
  useNodesState,
  useReactFlow,
  type Connection as FlowConnection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api, subscribeEvents } from "./api";
import { CredentialsDialog, SettingsDialog } from "./components/Dialogs";
import Inspector from "./components/Inspector";
import LogDrawer from "./components/LogDrawer";
import Palette, { DRAG_MIME } from "./components/Palette";
import StudioNodeView from "./components/StudioNode";
import { blankWorkflow, fromFlow, makeEdge, newNodeId, randomId, toFlow, type StudioNode, type WorkflowMeta } from "./graph";
import type {
  CredentialSummary,
  ExecutionEvent,
  ExecutionResult,
  ExecutionSummary,
  NodeDefinition,
  NodeStatus,
  NodeTypeInfo,
  ServiceStatus,
  WorkflowDefinition,
  WorkflowSummary,
} from "./types";

const NODE_TYPES = { studio: StudioNodeView };
const EVENT_TO_STATUS: Record<string, NodeStatus> = {
  "node.started": "running", "node.succeeded": "success", "node.failed": "failed",
  "node.skipped": "skipped", "node.cancelled": "cancelled",
};
const MAX_EVENTS = 3000;

function splitMeta(wf: WorkflowDefinition): WorkflowMeta {
  const { nodes: _n, connections: _c, ...meta } = wf;
  return meta;
}

export default function App() {
  const flow = useReactFlow();
  const [catalog, setCatalog] = useState<NodeTypeInfo[]>([]);
  const catalogMap = useMemo(() => new Map(catalog.map((c) => [c.type, c])), [catalog]);
  const [workflows, setWorkflows] = useState<WorkflowSummary[]>([]);
  const [meta, setMeta] = useState<WorkflowMeta>(() => splitMeta(blankWorkflow()));
  const [nodes, setNodes, onNodesChangeBase] = useNodesState<StudioNode>([]);
  const [edges, setEdges, onEdgesChangeBase] = useEdgesState<Edge>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [savedOnce, setSavedOnce] = useState(false);
  const [active, setActive] = useState(false);
  const [problems, setProblems] = useState<string[]>([]);
  const [toast, setToast] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const [execId, setExecId] = useState<string | null>(null);
  const execIdRef = useRef<string | null>(null);
  const [events, setEvents] = useState<ExecutionEvent[]>([]);
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [history, setHistory] = useState<ExecutionSummary[]>([]);
  const [status, setStatus] = useState<ServiceStatus | null>(null);
  const [connected, setConnected] = useState(false);
  const [credentials, setCredentials] = useState<CredentialSummary[]>([]);
  const [dialog, setDialog] = useState<null | "credentials" | "settings">(null);
  const [drawerOpen, setDrawerOpen] = useState(true);
  const fileInput = useRef<HTMLInputElement>(null);
  const workflowIdRef = useRef(meta.id);
  useEffect(() => { workflowIdRef.current = meta.id; }, [meta.id]);

  const notify = useCallback((kind: "ok" | "error", text: string) => {
    setToast({ kind, text });
    window.setTimeout(() => setToast((t) => (t?.text === text ? null : t)), kind === "error" ? 8000 : 3500);
  }, []);

  // ---------------------------------------------------------------- loading

  const refreshWorkflows = useCallback(() => api.listWorkflows().then(setWorkflows).catch(() => undefined), []);
  const refreshCredentials = useCallback(() => api.listCredentials().then(setCredentials).catch(() => undefined), []);
  const refreshStatus = useCallback(() => api.status().then(setStatus).catch(() => setStatus(null)), []);
  const refreshHistory = useCallback(
    (workflowId?: string) => api.listExecutions(workflowId).then(setHistory).catch(() => undefined), []);

  const loadDefinition = useCallback((wf: WorkflowDefinition, opts: { saved: boolean; active: boolean; dirty?: boolean }) => {
    const { nodes: n, edges: e } = toFlow(wf, catalogMap);
    setNodes(n);
    setEdges(e);
    setMeta(splitMeta(wf));
    setSavedOnce(opts.saved);
    setActive(opts.active);
    setDirty(Boolean(opts.dirty)); // an untouched new workflow has nothing to lose
    setSelectedId(null);
    setExecId(null);
    execIdRef.current = null;
    setResult(null);
    setProblems([]);
    refreshHistory(wf.id);
    window.setTimeout(() => flow.fitView({ padding: 0.25, maxZoom: 1.2 }), 50);
  }, [catalogMap, flow, refreshHistory, setEdges, setNodes]);

  useEffect(() => {
    api.nodeTypes().then(setCatalog).catch((e) => notify("error", `Cannot reach the service: ${e.message}`));
    refreshWorkflows();
    refreshCredentials();
    refreshStatus();
    const timer = window.setInterval(refreshStatus, 5000);
    return () => window.clearInterval(timer);
  }, [notify, refreshCredentials, refreshStatus, refreshWorkflows]);

  // first load: open the most recent workflow, or a blank one
  const initialised = useRef(false);
  useEffect(() => {
    if (initialised.current || !catalog.length) return;
    initialised.current = true;
    const last = localStorage.getItem("studio.lastWorkflow");
    if (last) {
      api.getWorkflow(last)
        .then((r) => loadDefinition(r.workflow, { saved: true, active: r.active }))
        .catch(() => loadDefinition(blankWorkflow(), { saved: false, active: false }));
    } else {
      loadDefinition(blankWorkflow(), { saved: false, active: false });
    }
  }, [catalog, loadDefinition]);

  useEffect(() => {
    if (savedOnce) {
      try { localStorage.setItem("studio.lastWorkflow", meta.id); } catch { /* storage unavailable */ }
    }
  }, [meta.id, savedOnce]);

  // keep node type info attached when the catalog arrives after the graph
  useEffect(() => {
    setNodes((ns) => ns.map((n) => (n.data.info ? n : { ...n, data: { ...n.data, info: catalogMap.get(n.data.def.type) } })));
  }, [catalogMap, setNodes]);

  // ---------------------------------------------------------------- live events

  useEffect(() => subscribeEvents((event) => {
    setEvents((evs) => (evs.length >= MAX_EVENTS ? [...evs.slice(-MAX_EVENTS / 2), event] : [...evs, event]));
    if (event.type === "execution.finished") refreshHistory(workflowIdRef.current);
  }, setConnected), [refreshHistory]);

  const currentEvents = useMemo(() => events.filter((e) => e.execution_id === execId), [events, execId]);
  const finished = currentEvents.some((e) => e.type === "execution.finished");
  const running = Boolean(execId) && !result && !finished;

  // Fetch the full result once the run is known to be finished. Fast runs can finish before the
  // POST /run response arrives, so this reacts to (execId, finished) in either order.
  const fetchedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!execId || !finished || result?.execution_id === execId || fetchedFor.current === execId) return;
    fetchedFor.current = execId;
    const id = execId;
    const attempt = (n: number) => api.getExecution(id).then((r) => {
      if (execIdRef.current === id) setResult(r);
    }).catch(() => { if (n < 5) window.setTimeout(() => attempt(n + 1), 250 * n); });
    attempt(1);
  }, [execId, finished, result]);

  const statusMap = useMemo(() => {
    const map: Record<string, NodeStatus> = {};
    if (!execId) return map;
    if (result && result.execution_id === execId) {
      for (const [id, rec] of Object.entries(result.nodes)) map[id] = rec.status;
      return map;
    }
    nodes.forEach((n) => (map[n.id] = "pending"));
    for (const e of currentEvents) if (e.node_id && EVENT_TO_STATUS[e.type]) map[e.node_id] = EVENT_TO_STATUS[e.type];
    return map;
  }, [currentEvents, execId, nodes, result]);

  const displayNodes = useMemo(
    () => nodes.map((n) => (n.data.status === statusMap[n.id] ? n : { ...n, data: { ...n.data, status: statusMap[n.id] } })),
    [nodes, statusMap]);

  // ---------------------------------------------------------------- editing

  const onNodesChange = useCallback((changes: NodeChange<StudioNode>[]) => {
    if (changes.some((c) => c.type === "remove" || c.type === "add" || (c.type === "position" && c.dragging === false))) setDirty(true);
    onNodesChangeBase(changes);
  }, [onNodesChangeBase]);

  const onEdgesChange = useCallback((changes: EdgeChange<Edge>[]) => {
    if (changes.some((c) => c.type === "remove")) setDirty(true);
    onEdgesChangeBase(changes);
  }, [onEdgesChangeBase]);

  const onConnect = useCallback((c: FlowConnection) => {
    if (!c.source || !c.target || c.source === c.target) return;
    const edge = makeEdge(c.source, c.target, c.sourceHandle ?? "main");
    setEdges((eds) => (eds.some((e) => e.id === edge.id) ? eds : [...eds, edge]));
    setDirty(true);
  }, [setEdges]);

  const addNode = useCallback((type: string, position?: { x: number; y: number }) => {
    const info = catalogMap.get(type);
    setNodes((ns) => {
      const id = newNodeId(type, new Set(ns.map((n) => n.id)));
      const pos = position ?? (() => {
        const pane = document.querySelector(".canvas")?.getBoundingClientRect();
        const center = flow.screenToFlowPosition({ x: (pane?.left ?? 0) + (pane?.width ?? 800) / 2, y: (pane?.top ?? 0) + (pane?.height ?? 600) / 2 });
        return { x: center.x - 90 + ns.length * 12, y: center.y - 30 + ns.length * 12 };
      })();
      const def: NodeDefinition = { id, type, parameters: {}, credentials: {} };
      window.setTimeout(() => setSelectedId(id), 0);
      return [...ns.map((n) => ({ ...n, selected: false })), { id, type: "studio", position: pos, selected: true, data: { def, info } }];
    });
    setDirty(true);
  }, [catalogMap, flow, setNodes]);

  const updateNodeDef = useCallback((def: NodeDefinition) => {
    setNodes((ns) => ns.map((n) => (n.id === def.id ? { ...n, data: { ...n.data, def } } : n)));
    setDirty(true);
  }, [setNodes]);

  const deleteNode = useCallback((id: string) => {
    setNodes((ns) => ns.filter((n) => n.id !== id));
    setEdges((es) => es.filter((e) => e.source !== id && e.target !== id));
    setSelectedId(null);
    setDirty(true);
  }, [setEdges, setNodes]);

  const definition = useCallback(() => fromFlow(meta, nodes, edges), [edges, meta, nodes]);

  // ---------------------------------------------------------------- commands

  const save = useCallback(async (): Promise<boolean> => {
    try {
      const res = await api.saveWorkflow(definition());
      setProblems(res.errors);
      setDirty(false);
      setSavedOnce(true);
      refreshWorkflows();
      refreshStatus();
      notify(res.errors.length ? "error" : "ok", res.errors.length ? "Saved, but the workflow has problems (see banner)." : "Saved.");
      return true;
    } catch (e) {
      notify("error", (e as Error).message);
      return false;
    }
  }, [definition, notify, refreshStatus, refreshWorkflows]);

  const run = useCallback(async () => {
    const selected = nodes.find((n) => n.id === selectedId);
    const startNode = selected?.data.info?.is_trigger ? selected.id : undefined;
    try {
      const res = await api.run(definition(), startNode);
      execIdRef.current = res.execution_id;
      setExecId(res.execution_id);
      setResult(null);
      setProblems([]);
      setDrawerOpen(true);
    } catch (e) {
      if (e instanceof ApiError) setProblems(e.errors);
      notify("error", "Cannot run: " + (e as Error).message.split("\n")[0]);
    }
  }, [definition, nodes, notify, selectedId]);

  const toggleActive = useCallback(async () => {
    if (!savedOnce || dirty) {
      if (!(await save())) return;
    }
    try {
      const res = await api.setActive(meta.id, !active);
      setActive(res.active);
      refreshWorkflows();
      refreshStatus();
      if (res.error) notify("error", `Activation failed: ${res.error}`);
      else if (res.active) notify("ok", res.triggers.length ? `Active: ${res.triggers.join("; ")}` : "Active, but there are no webhook/folder/schedule triggers.");
      else notify("ok", "Deactivated.");
    } catch (e) {
      if (e instanceof ApiError) setProblems(e.errors);
      notify("error", (e as Error).message.split("\n")[0]);
    }
  }, [active, dirty, meta.id, notify, refreshStatus, refreshWorkflows, save, savedOnce]);

  const openWorkflow = useCallback(async (id: string) => {
    if (dirty && !confirm("Discard unsaved changes?")) return;
    try {
      const res = await api.getWorkflow(id);
      loadDefinition(res.workflow, { saved: true, active: res.active });
      setProblems(res.errors);
    } catch (e) {
      notify("error", (e as Error).message);
    }
  }, [dirty, loadDefinition, notify]);

  const newWorkflow = useCallback(() => {
    if (dirty && !confirm("Discard unsaved changes?")) return;
    loadDefinition(blankWorkflow(), { saved: false, active: false });
  }, [dirty, loadDefinition]);

  const deleteWorkflow = useCallback(async () => {
    if (!confirm(`Delete “${meta.name}” and its run history?`)) return;
    await api.deleteWorkflow(meta.id);
    refreshWorkflows();
    loadDefinition(blankWorkflow(), { saved: false, active: false });
  }, [loadDefinition, meta.id, meta.name, refreshWorkflows]);

  const exportJson = useCallback(async () => {
    const content = JSON.stringify(definition(), null, 2);
    const filename = `${meta.name.replace(/[^\w-]+/g, "_") || "workflow"}.json`;
    const desktop = window.pywebview?.api;
    if (desktop?.save_json) {
      // The desktop window can't download files, so it saves through a native dialog.
      try {
        const path = await desktop.save_json(filename, content);
        if (path) notify("ok", `Exported to ${path}`);
      } catch (e) {
        notify("error", `Export failed: ${(e as Error).message ?? e}`);
      }
      return;
    }
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([content], { type: "application/json" }));
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    // Revoking straight away can cancel the download before the browser reads the blob.
    setTimeout(() => URL.revokeObjectURL(a.href), 10_000);
  }, [definition, meta.name, notify]);

  const importJson = useCallback(async (file: File) => {
    try {
      const wf = JSON.parse((await file.text()).replace(/^﻿/, "")) as WorkflowDefinition;
      if (!Array.isArray(wf.nodes)) throw new Error("not a workflow file (no nodes)");
      wf.id ||= randomId();
      wf.connections ||= [];
      wf.nodes = wf.nodes.map((n) => ({ ...n, parameters: n.parameters ?? {}, credentials: n.credentials ?? {} }));
      loadDefinition(wf, { saved: false, active: false, dirty: true });
      notify("ok", `Imported “${wf.name}”. Save to keep it.`);
    } catch (e) {
      notify("error", `Import failed: ${(e as Error).message}`);
    }
  }, [loadDefinition, notify]);

  const openExecution = useCallback(async (id: string) => {
    try {
      const res = await api.getExecution(id);
      execIdRef.current = id;
      setExecId(id);
      setResult(res);
    } catch (e) {
      notify("error", (e as Error).message);
    }
  }, [notify]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [run, save]);

  useEffect(() => {
    const onUnload = (e: BeforeUnloadEvent) => { if (dirty) e.preventDefault(); };
    window.addEventListener("beforeunload", onUnload);
    return () => window.removeEventListener("beforeunload", onUnload);
  }, [dirty]);

  // ---------------------------------------------------------------- render

  const selectedNode = displayNodes.find((n) => n.id === selectedId) ?? null;
  const record = selectedNode && result?.execution_id === execId ? result?.nodes[selectedNode.id] : undefined;
  const tunnelUp = status?.tunnel.state === "running";

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Automation Studio</div>
        <input className="wf-name" value={meta.name} aria-label="Workflow name"
          onChange={(e) => { setMeta({ ...meta, name: e.target.value }); setDirty(true); }} />
        {dirty ? <span className="badge">unsaved</span> : !savedOnce && <span className="badge muted-badge">new</span>}
        <span className="spacer" />
        <button onClick={save} title="Ctrl+S">Save</button>
        <button className="primary" onClick={run} disabled={running} title="Ctrl+Enter (runs the selected trigger, or all triggers with their sample data)">
          {running ? "Running…" : "▶ Run"}
        </button>
        <label className={`switch ${active ? "on" : ""}`} title="Active workflows keep listening for webhooks, files and schedules in the background">
          <input type="checkbox" checked={active} onChange={toggleActive} />
          <span className="switch-track"><span className="switch-thumb" /></span>
          {active ? "Active" : "Inactive"}
        </label>
        <span className="sep" />
        {status?.updates.available && status.updates.latest && (
          <button className="update-pill" onClick={() => setDialog("settings")} title="An update is available">
            ↑ v{status.updates.latest.version}
          </button>
        )}
        <button className="ghost" onClick={() => setDialog("credentials")}>Credentials</button>
        <button className="ghost" onClick={() => setDialog("settings")}>
          Settings {tunnelUp && <span className="dot st-success" title="public tunnel running" />}
        </button>
      </header>

      <aside className="sidebar">
        <div className="side-section">
          <div className="side-head">
            <span>Workflows</span>
            <span>
              <button className="ghost small" onClick={() => fileInput.current?.click()} title="Import a workflow JSON file">Import</button>
              <button className="ghost small" onClick={newWorkflow}>+ New</button>
            </span>
          </div>
          <input ref={fileInput} type="file" accept=".json,application/json" hidden
            onChange={(e) => { const f = e.target.files?.[0]; if (f) importJson(f); e.target.value = ""; }} />
          <div className="wf-list">
            {workflows.map((w) => (
              <button key={w.id} className={`wf-item ${w.id === meta.id ? "current" : ""}`} onClick={() => openWorkflow(w.id)}>
                <span className={`dot ${w.active ? "st-success" : "idle"}`} title={w.active ? "active" : "inactive"} />
                <span className="wf-item-name">{w.name}</span>
              </button>
            ))}
            {!workflows.length && <div className="muted pad small">No saved workflows yet.</div>}
          </div>
          <div className="side-actions">
            <button className="ghost small" onClick={exportJson}>Export JSON</button>
            {savedOnce && <button className="ghost small danger-text" onClick={deleteWorkflow}>Delete</button>}
          </div>
        </div>
        <div className="side-section grow">
          <div className="side-head"><span>Nodes</span></div>
          <Palette catalog={catalog} onAdd={(t) => addNode(t)} />
        </div>
      </aside>

      <main className="canvas" onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
        onDrop={(e) => {
          const type = e.dataTransfer.getData(DRAG_MIME);
          if (type) { e.preventDefault(); addNode(type, flow.screenToFlowPosition({ x: e.clientX - 90, y: e.clientY - 25 })); }
        }}>
        {problems.length > 0 && (
          <div className="problems">
            <b>Problems</b>
            <ul>{problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
            <button className="ghost small" onClick={() => setProblems([])}>dismiss</button>
          </div>
        )}
        <ReactFlow
          nodes={displayNodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeClick={(_, n) => setSelectedId(n.id)}
          onPaneClick={() => setSelectedId(null)}
          isValidConnection={(c) => c.source !== c.target}
          deleteKeyCode={["Delete", "Backspace"]}
          colorMode="dark"
          defaultEdgeOptions={{ animated: false }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.2}
          maxZoom={2}
          fitView
        >
          <Background gap={20} size={1} />
          <Controls />
          <MiniMap pannable zoomable nodeStrokeWidth={3} style={{ width: 170, height: 110 }} />
        </ReactFlow>
      </main>

      <aside className="right">
        <Inspector
          node={selectedNode}
          meta={meta}
          record={record}
          credentials={credentials}
          status={status}
          onNodeChange={updateNodeDef}
          onMetaChange={(m) => { setMeta(m); setDirty(true); }}
          onDeleteNode={deleteNode}
          onManageCredentials={() => setDialog("credentials")}
        />
      </aside>

      <LogDrawer
        open={drawerOpen}
        onToggle={() => setDrawerOpen(!drawerOpen)}
        currentEvents={currentEvents}
        allEvents={events}
        history={history}
        running={running}
        onCancel={() => execId && api.cancel(execId)}
        onOpenExecution={openExecution}
        connected={connected}
      />

      {dialog === "credentials" && (
        <CredentialsDialog credentials={credentials} notify={notify} onChanged={refreshCredentials} onClose={() => setDialog(null)} />
      )}
      {dialog === "settings" && (
        <SettingsDialog status={status} credentials={credentials} notify={notify} onChanged={refreshStatus} onClose={() => setDialog(null)} />
      )}
      {toast && <div className={`toast ${toast.kind}`} onClick={() => setToast(null)}>{toast.text}</div>}
    </div>
  );
}
