import type {
  CredentialSummary,
  CredentialTypes,
  ExecutionEvent,
  ExecutionResult,
  ExecutionSummary,
  NodeTypeInfo,
  ServiceStatus,
  TunnelSettings,
  TunnelStatus,
  UpdateStatus,
  WorkflowDefinition,
  WorkflowSummary,
} from "./types";

const TOKEN = document.querySelector<HTMLMetaElement>('meta[name="studio-token"]')?.content ?? "";

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(ApiError.describe(detail, status));
  }
  static describe(detail: unknown, status: number): string {
    const d = (detail as any)?.detail ?? detail;
    if (d?.errors) return (d.errors as string[]).join("\n");
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((e: any) => `${(e.loc ?? []).join(".")}: ${e.msg}`).join("\n");
    return `HTTP ${status}`;
  }
  get errors(): string[] {
    const d = (this.detail as any)?.detail;
    return d?.errors ?? [this.message];
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(`/api${path}`, {
    method,
    headers: { "X-Studio-Token": TOKEN, ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  const data = text ? JSON.parse(text) : null;
  if (!resp.ok) throw new ApiError(resp.status, data);
  return data as T;
}

export const api = {
  status: () => request<ServiceStatus>("GET", "/status"),
  nodeTypes: () => request<NodeTypeInfo[]>("GET", "/node-types"),
  listWorkflows: () => request<WorkflowSummary[]>("GET", "/workflows"),
  getWorkflow: (id: string) =>
    request<{ workflow: WorkflowDefinition; active: boolean; errors: string[] }>("GET", `/workflows/${encodeURIComponent(id)}`),
  saveWorkflow: (wf: WorkflowDefinition) =>
    request<{ workflow: WorkflowDefinition; errors: string[] }>("POST", "/workflows", wf),
  deleteWorkflow: (id: string) => request<{ deleted: boolean }>("DELETE", `/workflows/${encodeURIComponent(id)}`),
  setActive: (id: string, active: boolean) =>
    request<{ active: boolean; triggers: string[]; error: string | null }>(
      "POST", `/workflows/${encodeURIComponent(id)}/active`, { active }),
  validate: (wf: WorkflowDefinition) => request<{ errors: string[] }>("POST", "/validate", wf),
  run: (wf: WorkflowDefinition, startNode?: string) =>
    request<{ execution_id: string }>("POST", "/workflows/run", { workflow: wf, start_node: startNode ?? null }),
  cancel: (id: string) => request<{ cancelled: boolean }>("POST", `/executions/${id}/cancel`),
  listExecutions: (workflowId?: string, limit = 30) =>
    request<ExecutionSummary[]>("GET", `/executions?limit=${limit}${workflowId ? `&workflow_id=${encodeURIComponent(workflowId)}` : ""}`),
  getExecution: (id: string) => request<ExecutionResult>("GET", `/executions/${id}`),
  listCredentials: () => request<CredentialSummary[]>("GET", "/credentials"),
  credentialTypes: () => request<CredentialTypes>("GET", "/credential-types"),
  saveCredential: (name: string, type: string, data: Record<string, string>) =>
    request<{ saved: string }>("POST", "/credentials", { name, type, data }),
  deleteCredential: (name: string) => request<{ deleted: boolean }>("DELETE", `/credentials/${encodeURIComponent(name)}`),
  setTunnel: (settings: TunnelSettings) =>
    request<{ settings: TunnelSettings; status: TunnelStatus }>("PUT", "/tunnel", settings),
  setAutostart: (enabled: boolean) => request<ServiceStatus["autostart"]>("PUT", "/autostart", { enabled }),
  checkUpdates: () => request<UpdateStatus>("POST", "/updates/check"),
  setUpdateSettings: (source: string | null, autoCheck: boolean) =>
    request<UpdateStatus>("PUT", "/updates/settings", { source, auto_check: autoCheck }),
  installUpdate: () => request<{ installing: string }>("POST", "/updates/install"),
};

/** Live execution events; reconnects automatically. Returns a disposer. */
export function subscribeEvents(onEvent: (e: ExecutionEvent) => void, onState: (connected: boolean) => void): () => void {
  let socket: WebSocket | null = null;
  let closed = false;
  let retry = 500;

  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    socket = new WebSocket(`${proto}://${location.host}/ws/logs?token=${encodeURIComponent(TOKEN)}`);
    socket.onopen = () => {
      retry = 500;
      onState(true);
    };
    socket.onmessage = (msg) => onEvent(JSON.parse(msg.data));
    socket.onclose = () => {
      onState(false);
      if (!closed) setTimeout(open, (retry = Math.min(retry * 2, 8000)));
    };
  };
  open();
  return () => {
    closed = true;
    socket?.close();
  };
}
