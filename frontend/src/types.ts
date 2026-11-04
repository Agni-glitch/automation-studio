// Mirrors engine/models.py and backend/server.py payloads.

export type JsonSchema = {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  const?: unknown;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  minimum?: number;
  maximum?: number;
  exclusiveMinimum?: number;
  pattern?: string;
};

export type NodeTypeInfo = {
  type: string;
  display_name: string;
  category: "trigger" | "ai" | "code" | "action" | "logic";
  description: string;
  is_trigger: boolean;
  outputs: string[];
  credential_slots: Record<string, string>;
  parameters_schema: JsonSchema;
};

export type OnError = "stop" | "continue" | "error_output";

export type NodeDefinition = {
  id: string;
  type: string;
  name?: string | null;
  parameters: Record<string, unknown>;
  credentials: Record<string, string>;
  retry?: { max_attempts: number; backoff_seconds: number; backoff_multiplier?: number };
  timeout_seconds?: number | null;
  on_error?: OnError;
  disabled?: boolean;
  position?: [number, number] | null;
  notes?: string | null;
};

export type Connection = { source: string; target: string; source_output?: string };

export type WorkflowDefinition = {
  id: string;
  name: string;
  description?: string;
  version?: number;
  nodes: NodeDefinition[];
  connections: Connection[];
  variables?: Record<string, unknown>;
  settings?: { max_concurrency?: number; timeout_seconds?: number | null; fail_fast?: boolean };
};

export type WorkflowSummary = {
  id: string;
  name: string;
  description: string;
  active: boolean;
  updated_at: string;
};

export type NodeStatus = "pending" | "running" | "success" | "failed" | "skipped" | "cancelled";

export type NodeRunRecord = {
  node_id: string;
  node_type: string;
  node_name: string;
  status: NodeStatus;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
  output: unknown;
  active_outputs: string[];
  error: { type: string; message: string; traceback?: string | null } | null;
  error_handled: boolean;
  message: string | null;
  logs: { timestamp: string; level: string; message: string }[];
};

export type ExecutionResult = {
  execution_id: string;
  workflow_id: string;
  workflow_name: string;
  status: "running" | "success" | "failed" | "cancelled";
  started_at: string;
  finished_at: string | null;
  trigger_data: unknown;
  error: string | null;
  nodes: Record<string, NodeRunRecord>;
};

export type ExecutionSummary = {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: string;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};

export type ExecutionEvent = {
  type: string;
  execution_id: string;
  workflow_id: string;
  node_id: string | null;
  timestamp: string;
  payload: Record<string, any>;
};

export type CredentialSummary = { name: string; type: string; fields: string[]; updated_at: string };
export type CredentialTypes = Record<string, { label: string; fields: string[] }>;

export type TunnelStatus = {
  state: "stopped" | "downloading" | "starting" | "running" | "reconnecting" | "error";
  mode: string | null;
  public_url: string | null;
  webhook_base: string | null;
  error: string | null;
  installed: boolean;
  recent_log: string[];
};

export type TunnelSettings = { enabled: boolean; mode: "quick" | "token"; credential: string | null; hostname: string | null };

export type ServiceStatus = {
  version: string;
  pid: number;
  started_at: string;
  api_url: string;
  webhook_url: string;
  public_webhook_url: string | null;
  active_workflows: { workflow_id: string; name: string; triggers: string[]; running_executions: number }[];
  trigger_errors: Record<string, string>;
  webhooks: { method: string; path: string; workflow_id: string; workflow_name: string; public: string }[];
  running_executions: string[];
  tunnel: TunnelStatus;
  tunnel_settings: TunnelSettings;
  autostart: { supported: boolean; enabled: boolean; up_to_date?: boolean; command: string | null };
  updates: UpdateStatus;
  tray: boolean;
  frozen: boolean;
};

export type UpdateStatus = {
  current_version: string;
  source: string | null;
  state: "idle" | "checking" | "downloading" | "verifying" | "installing";
  checked_at: string | null;
  error: string | null;
  available: boolean;
  latest: { version: string; download_url: string | null; sha256: string | null; notes: string; page_url: string | null } | null;
  can_auto_install: boolean;
  auto_install_blocked_reason: string | null;
  auto_check?: boolean;
};
