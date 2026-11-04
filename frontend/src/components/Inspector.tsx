import { useState } from "react";
import type { WorkflowMeta, StudioNode } from "../graph";
import type { CredentialSummary, NodeDefinition, NodeRunRecord, OnError, ServiceStatus } from "../types";
import { JsonEditor, ReadonlyJson } from "./Editors";
import SchemaForm from "./SchemaForm";

type Tab = "parameters" | "settings" | "output";

type Props = {
  node: StudioNode | null;
  meta: WorkflowMeta;
  record?: NodeRunRecord;
  credentials: CredentialSummary[];
  status: ServiceStatus | null;
  onNodeChange: (def: NodeDefinition) => void;
  onMetaChange: (meta: WorkflowMeta) => void;
  onDeleteNode: (id: string) => void;
  onManageCredentials: () => void;
};

export default function Inspector(props: Props) {
  if (!props.node) return <WorkflowPanel meta={props.meta} onChange={props.onMetaChange} />;
  return <NodePanel key={props.node.id} {...props} node={props.node} />;
}

function NodePanel({ node, record, credentials, status, onNodeChange, onDeleteNode, onManageCredentials }: Props & { node: StudioNode }) {
  const [tab, setTab] = useState<Tab>(record ? "output" : "parameters");
  const { def, info } = node.data;
  const update = (patch: Partial<NodeDefinition>) => onNodeChange({ ...def, ...patch });

  return (
    <div className="inspector">
      <div className="insp-head">
        <input className="insp-title" value={def.name ?? ""} placeholder={def.id}
          onChange={(e) => update({ name: e.target.value || null })} />
        <div className="muted small">{info?.display_name ?? def.type} · id <code>{def.id}</code></div>
        {info?.description && <div className="hint">{info.description}</div>}
      </div>
      <div className="tabs">
        {(["parameters", "settings", "output"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t}{t === "output" && record ? <span className={`dot st-${record.status}`} /> : null}
          </button>
        ))}
      </div>
      <div className="insp-body">
        {tab === "parameters" && (
          <>
            {def.type === "trigger.webhook" && <WebhookUrls def={def} status={status} />}
            {info ? (
              <SchemaForm schema={info.parameters_schema} value={def.parameters}
                onChange={(parameters) => update({ parameters })} />
            ) : (
              <div className="error-box">Unknown node type “{def.type}”.</div>
            )}
          </>
        )}
        {tab === "settings" && (
          <div className="form">
            {Object.entries(info?.credential_slots ?? {}).map(([slot, hint]) => (
              <div className="field" key={slot}>
                <div className="field-label"><span>Credential{slot !== "default" ? ` (${slot})` : ""}</span>
                  <button type="button" className="link" onClick={onManageCredentials}>manage</button></div>
                <select value={def.credentials[slot] ?? ""} onChange={(e) => {
                  const credentialsMap = { ...def.credentials };
                  if (e.target.value) credentialsMap[slot] = e.target.value;
                  else delete credentialsMap[slot];
                  update({ credentials: credentialsMap });
                }}>
                  <option value="">— none —</option>
                  {credentials.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.fields.join(", ")})</option>)}
                  {def.credentials[slot] && !credentials.some((c) => c.name === def.credentials[slot]) && (
                    <option value={def.credentials[slot]}>{def.credentials[slot]} (missing!)</option>
                  )}
                </select>
                <div className="hint">Expects {hint}</div>
              </div>
            ))}
            <div className="field">
              <div className="field-label"><span>On error</span></div>
              <select value={def.on_error ?? "stop"} onChange={(e) => update({ on_error: e.target.value as OnError })}>
                <option value="stop">Stop the workflow</option>
                <option value="continue">Continue (error data on main output)</option>
                <option value="error_output">Continue on a separate “error” output</option>
              </select>
            </div>
            <div className="row2">
              <div className="field">
                <div className="field-label"><span>Retries (attempts)</span></div>
                <input inputMode="numeric" value={def.retry?.max_attempts ?? 1} onChange={(e) =>
                  update({ retry: { backoff_seconds: 1, ...def.retry, max_attempts: Math.max(1, Math.min(10, Number(e.target.value) || 1)) } })} />
              </div>
              <div className="field">
                <div className="field-label"><span>Backoff (s)</span></div>
                <input inputMode="decimal" value={def.retry?.backoff_seconds ?? 1} onChange={(e) =>
                  update({ retry: { max_attempts: 1, ...def.retry, backoff_seconds: Math.max(0, Number(e.target.value) || 0) } })} />
              </div>
            </div>
            <div className="field">
              <div className="field-label"><span>Timeout (seconds)</span></div>
              <input inputMode="decimal" value={def.timeout_seconds ?? ""} placeholder="default: 300"
                onChange={(e) => update({ timeout_seconds: e.target.value ? Number(e.target.value) : undefined })} />
            </div>
            <label className="check">
              <input type="checkbox" checked={Boolean(def.disabled)} onChange={(e) => update({ disabled: e.target.checked })} />
              Disabled (passes its input through)
            </label>
            <div className="field">
              <div className="field-label"><span>Notes</span></div>
              <textarea rows={3} value={def.notes ?? ""} onChange={(e) => update({ notes: e.target.value || null })} />
            </div>
            <button className="danger" onClick={() => onDeleteNode(def.id)}>Delete node</button>
          </div>
        )}
        {tab === "output" && <OutputView record={record} />}
      </div>
    </div>
  );
}

function WebhookUrls({ def, status }: { def: NodeDefinition; status: ServiceStatus | null }) {
  const path = String(def.parameters.path ?? "").replace(/^\/+|\/+$/g, "");
  const method = String(def.parameters.method ?? "POST");
  if (!status || !path) return null;
  const publicAllowed = Boolean(def.parameters.allow_public) || def.parameters.auth === "header";
  return (
    <div className="info-box">
      <div><b>{method}</b> <code className="copyable">{status.webhook_url}{path}</code></div>
      {status.public_webhook_url ? (
        <div>
          Public: <code className="copyable">{status.public_webhook_url}{path}</code>
          {!publicAllowed && <div className="warn small">Public calls are refused until you enable token auth or “allow public”.</div>}
        </div>
      ) : (
        <div className="muted small">Turn on the public tunnel in Settings to receive calls from the internet.</div>
      )}
      <div className="muted small">Listens only while the workflow is saved and active.</div>
    </div>
  );
}

function OutputView({ record }: { record?: NodeRunRecord }) {
  if (!record) return <div className="muted">Run the workflow to see this node’s output.</div>;
  const duration = record.started_at && record.finished_at
    ? `${Math.round(new Date(record.finished_at).getTime() - new Date(record.started_at).getTime())} ms` : "";
  return (
    <div className="output">
      <div className="output-meta">
        <span className={`pill st-${record.status}`}>{record.status}</span>
        {duration && <span className="muted">{duration}</span>}
        {record.attempts > 1 && <span className="muted">{record.attempts} attempts</span>}
        {record.active_outputs.length > 0 && <span className="muted">→ {record.active_outputs.join(", ")}</span>}
      </div>
      {record.message && <div className="muted">{record.message}</div>}
      {record.error && (
        <div className="error-box">
          <b>{record.error.type}</b>: {record.error.message}
          {record.error.traceback && <details><summary>traceback</summary><pre>{record.error.traceback}</pre></details>}
        </div>
      )}
      {record.logs.length > 0 && (
        <div className="node-logs">
          {record.logs.map((l, i) => <div key={i} className={`log-${l.level}`}>{l.level.toUpperCase()} {l.message}</div>)}
        </div>
      )}
      {record.output !== null && record.output !== undefined && (
        <>
          <div className="section-label">Output</div>
          <ReadonlyJson value={record.output} />
        </>
      )}
    </div>
  );
}

function WorkflowPanel({ meta, onChange }: { meta: WorkflowMeta; onChange: (m: WorkflowMeta) => void }) {
  const settings = meta.settings ?? {};
  return (
    <div className="inspector">
      <div className="insp-head">
        <div className="insp-title-static">Workflow settings</div>
        <div className="muted small">Select a node to edit it.</div>
      </div>
      <div className="insp-body form">
        <div className="field">
          <div className="field-label"><span>Description</span></div>
          <textarea rows={2} value={meta.description ?? ""} onChange={(e) => onChange({ ...meta, description: e.target.value })} />
        </div>
        <div className="field">
          <div className="field-label"><span>Variables</span></div>
          <JsonEditor value={meta.variables ?? {}} onChange={(v) => onChange({ ...meta, variables: (v as Record<string, unknown>) ?? {} })} />
          <div className="hint">Use as <code>{"{{ vars.name }}"}</code> in any node.</div>
        </div>
        <div className="row2">
          <div className="field">
            <div className="field-label"><span>Max parallel nodes</span></div>
            <input inputMode="numeric" value={settings.max_concurrency ?? 4} onChange={(e) =>
              onChange({ ...meta, settings: { ...settings, max_concurrency: Math.max(1, Number(e.target.value) || 1) } })} />
          </div>
          <div className="field">
            <div className="field-label"><span>Timeout (s)</span></div>
            <input inputMode="decimal" value={settings.timeout_seconds ?? ""} placeholder="none" onChange={(e) =>
              onChange({ ...meta, settings: { ...settings, timeout_seconds: e.target.value ? Number(e.target.value) : null } })} />
          </div>
        </div>
        <label className="check">
          <input type="checkbox" checked={settings.fail_fast ?? true}
            onChange={(e) => onChange({ ...meta, settings: { ...settings, fail_fast: e.target.checked } })} />
          Stop everything on the first unhandled failure
        </label>
        <div className="muted small">Workflow id: <code>{meta.id}</code></div>
      </div>
    </div>
  );
}
