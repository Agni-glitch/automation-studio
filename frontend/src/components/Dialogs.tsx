import { useEffect, useState, type ReactNode } from "react";
import { api } from "../api";
import type { CredentialSummary, CredentialTypes, ServiceStatus, TunnelSettings } from "../types";

const SECRET = /key|token|password|secret/i;

export function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-label={title}>
        <div className="modal-head"><h2>{title}</h2><button className="ghost" onClick={onClose}>✕</button></div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function CredentialsDialog({ credentials, onChanged, onClose, notify }: {
  credentials: CredentialSummary[];
  onChanged: () => void;
  onClose: () => void;
  notify: (kind: "ok" | "error", text: string) => void;
}) {
  const [types, setTypes] = useState<CredentialTypes>({});
  const [name, setName] = useState("");
  const [type, setType] = useState("api_key");
  const [fields, setFields] = useState<{ key: string; value: string }[]>([{ key: "api_key", value: "" }]);

  useEffect(() => { api.credentialTypes().then(setTypes).catch(() => undefined); }, []);

  const pickType = (t: string) => {
    setType(t);
    const template = types[t]?.fields ?? [];
    setFields(template.length ? template.map((key) => ({ key, value: "" })) : [{ key: "", value: "" }]);
  };

  const save = async () => {
    const data = Object.fromEntries(fields.filter((f) => f.key.trim()).map((f) => [f.key.trim(), f.value]));
    if (!name.trim() || !Object.keys(data).length) return notify("error", "Give the credential a name and at least one field.");
    try {
      await api.saveCredential(name.trim(), type, data);
      notify("ok", `Saved credential “${name.trim()}” (encrypted).`);
      setName("");
      pickType(type);
      onChanged();
    } catch (e) {
      notify("error", (e as Error).message);
    }
  };

  return (
    <Modal title="Credentials" onClose={onClose}>
      <p className="muted">Stored encrypted on this PC (locked to your Windows account). Secret values are never shown again; save under the same name to replace one.</p>
      <table className="grid-table">
        <thead><tr><th>Name</th><th>Type</th><th>Fields</th><th>Updated</th><th /></tr></thead>
        <tbody>
          {credentials.map((c) => (
            <tr key={c.name}>
              <td><code>{c.name}</code></td><td>{c.type}</td><td>{c.fields.join(", ")}</td>
              <td>{new Date(c.updated_at).toLocaleDateString()}</td>
              <td><button className="danger small" onClick={async () => {
                if (!confirm(`Delete credential “${c.name}”? Nodes using it will fail.`)) return;
                await api.deleteCredential(c.name);
                onChanged();
              }}>Delete</button></td>
            </tr>
          ))}
          {!credentials.length && <tr><td colSpan={5} className="muted">No credentials yet.</td></tr>}
        </tbody>
      </table>
      <h3>Add or replace</h3>
      <div className="form">
        <div className="row2">
          <div className="field"><div className="field-label"><span>Name</span></div>
            <input value={name} placeholder="e.g. anthropic" onChange={(e) => setName(e.target.value)} /></div>
          <div className="field"><div className="field-label"><span>Type</span></div>
            <select value={type} onChange={(e) => pickType(e.target.value)}>
              {Object.entries(types).map(([k, v]) => <option key={k} value={k}>{v.label}</option>)}
            </select></div>
        </div>
        {fields.map((f, i) => (
          <div className="row2" key={i}>
            <input value={f.key} placeholder="field" onChange={(e) => setFields(fields.map((x, j) => j === i ? { ...x, key: e.target.value } : x))} />
            <input type={SECRET.test(f.key) ? "password" : "text"} value={f.value} placeholder="value" autoComplete="off"
              onChange={(e) => setFields(fields.map((x, j) => j === i ? { ...x, value: e.target.value } : x))} />
          </div>
        ))}
        <div className="actions">
          <button className="ghost" onClick={() => setFields([...fields, { key: "", value: "" }])}>+ field</button>
          <button className="primary" onClick={save}>Save credential</button>
        </div>
      </div>
    </Modal>
  );
}

export async function installUpdate(notify: (kind: "ok" | "error", text: string) => void) {
  if (!confirm("Download, verify and install the update? The app restarts; running workflows are stopped.")) return;
  try {
    const res = await api.installUpdate();
    notify("ok", `Installing ${res.installing}… the app will reopen when it's done.`);
  } catch (e) {
    notify("error", (e as Error).message);
  }
}

function UpdatesSection({ status, notify, onChanged }: {
  status: ServiceStatus;
  notify: (kind: "ok" | "error", text: string) => void;
  onChanged: () => void;
}) {
  const u = status.updates;
  const [source, setSource] = useState(u.source ?? "");
  const [autoCheck, setAutoCheck] = useState(u.auto_check ?? true);
  const [busy, setBusy] = useState(false);

  const saveAndCheck = async () => {
    setBusy(true);
    try {
      await api.setUpdateSettings(source.trim() || null, autoCheck);
      if (source.trim()) {
        const res = await api.checkUpdates();
        if (res.error) notify("error", res.error);
        else notify("ok", res.available ? `Version ${res.latest?.version} is available.` : "You're up to date.");
      }
      onChanged();
    } catch (e) {
      notify("error", (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h3>Updates</h3>
      <p className="muted">
        Version {u.current_version}{status.frozen ? "" : " (running from source)"}.
        Installers are only run if their signature or published SHA-256 checks out.
      </p>
      <div className="row2">
        <div className="field"><div className="field-label"><span>Update source</span></div>
          <input value={source} placeholder="github:owner/repo or https://…/latest.json" onChange={(e) => setSource(e.target.value)} /></div>
        <label className="check"><input type="checkbox" checked={autoCheck} onChange={(e) => setAutoCheck(e.target.checked)} />
          Check daily</label>
      </div>
      <div className="actions"><button className="primary" disabled={busy || u.state !== "idle"} onClick={saveAndCheck}>
        {u.state === "checking" ? "Checking…" : "Save & check now"}</button></div>
      {(u.checked_at || u.error) && (
        <div className="info-box">
          {u.available && u.latest ? (
            <>
              <div><b>Version {u.latest.version} is available.</b></div>
              {u.latest.notes && <details><summary>Release notes</summary><pre className="small">{u.latest.notes}</pre></details>}
              <div className="actions">
                {u.latest.page_url && <a className="link" href={u.latest.page_url} target="_blank" rel="noreferrer">Release page</a>}
                <button className="primary" disabled={!u.can_auto_install || u.state !== "idle"} onClick={() => installUpdate(notify)}>
                  {u.state === "downloading" ? "Downloading…" : u.state === "verifying" ? "Verifying…" : "Install update"}</button>
              </div>
              {!u.can_auto_install && <div className="muted small">{u.auto_install_blocked_reason}</div>}
            </>
          ) : !u.error && <div>You're up to date.</div>}
          {u.error && <div className="warn small">{u.error}</div>}
          {u.checked_at && <div className="muted small">Last checked {new Date(u.checked_at).toLocaleString()}</div>}
        </div>
      )}
    </>
  );
}

export function SettingsDialog({ status, credentials, onClose, onChanged, notify }: {
  status: ServiceStatus | null;
  credentials: CredentialSummary[];
  onClose: () => void;
  onChanged: () => void;
  notify: (kind: "ok" | "error", text: string) => void;
}) {
  const [tunnel, setTunnel] = useState<TunnelSettings>(
    status?.tunnel_settings ?? { enabled: false, mode: "quick", credential: null, hostname: null });
  const [busy, setBusy] = useState(false);
  if (!status) return <Modal title="Settings" onClose={onClose}><p>Service not reachable.</p></Modal>;
  const t = status.tunnel;

  const applyTunnel = async (next: TunnelSettings) => {
    setBusy(true);
    try {
      await api.setTunnel(next);
      setTunnel(next);
      onChanged();
    } catch (e) {
      notify("error", (e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Settings" onClose={onClose}>
      <h3>Background service</h3>
      <p className="muted">Runs your active workflows (webhooks, folder watchers, schedules) even when this window is closed.</p>
      <label className="check">
        <input type="checkbox" checked={status.autostart.enabled} disabled={!status.autostart.supported}
          onChange={async (e) => {
            try { await api.setAutostart(e.target.checked); onChanged(); } catch (err) { notify("error", (err as Error).message); }
          }} />
        Start automatically when I sign in to Windows
      </label>
      {status.autostart.enabled && status.autostart.up_to_date === false && (
        <div className="warn small">The app moved since this was enabled; toggle it off and on again.</div>
      )}
      <div className="muted small">Service pid {status.pid} · API {status.api_url} · webhooks {status.webhook_url}</div>

      <h3>Public webhooks (Cloudflare Tunnel)</h3>
      <p className="muted">
        Gives your webhooks a public HTTPS address so online services can call them. Only the webhook port is exposed,
        never this app. Public calls are refused unless a webhook uses token auth or has “allow public” enabled.
      </p>
      <label className="check">
        <input type="checkbox" checked={tunnel.enabled} disabled={busy} onChange={(e) => applyTunnel({ ...tunnel, enabled: e.target.checked })} />
        Enable public tunnel
      </label>
      <div className="row2">
        <label className="check"><input type="radio" checked={tunnel.mode === "quick"} onChange={() => setTunnel({ ...tunnel, mode: "quick" })} />
          Quick (no account, random URL that changes on restart)</label>
        <label className="check"><input type="radio" checked={tunnel.mode === "token"} onChange={() => setTunnel({ ...tunnel, mode: "token" })} />
          Named tunnel (stable URL, your Cloudflare account)</label>
      </div>
      {tunnel.mode === "token" && (
        <div className="row2">
          <div className="field"><div className="field-label"><span>Tunnel token credential</span></div>
            <select value={tunnel.credential ?? ""} onChange={(e) => setTunnel({ ...tunnel, credential: e.target.value || null })}>
              <option value="">— choose —</option>
              {credentials.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}
            </select></div>
          <div className="field"><div className="field-label"><span>Public hostname</span></div>
            <input value={tunnel.hostname ?? ""} placeholder="hooks.example.com" onChange={(e) => setTunnel({ ...tunnel, hostname: e.target.value || null })} /></div>
        </div>
      )}
      <div className="actions"><button className="primary" disabled={busy} onClick={() => applyTunnel(tunnel)}>Apply</button></div>
      <div className="info-box">
        <div>Status: <span className={`pill tunnel-${t.state}`}>{t.state}</span> {t.mode && <span className="muted">({t.mode})</span>}</div>
        {t.webhook_base && <div>Public webhook base: <code className="copyable">{t.webhook_base}</code>
          <button className="ghost small" onClick={() => navigator.clipboard.writeText(t.webhook_base!)}>copy</button></div>}
        {t.state === "downloading" && <div className="muted">Downloading cloudflared from Cloudflare’s GitHub releases…</div>}
        {t.error && t.state !== "running" && <div className="warn small">{t.error}</div>}
        {t.recent_log.length > 0 && <details><summary>cloudflared log</summary><pre className="small">{t.recent_log.join("\n")}</pre></details>}
      </div>

      <UpdatesSection status={status} notify={notify} onChanged={onChanged} />

      <h3>Listening webhooks</h3>
      <table className="grid-table">
        <thead><tr><th>Method</th><th>Path</th><th>Workflow</th><th>Public</th></tr></thead>
        <tbody>
          {status.webhooks.map((w) => (
            <tr key={w.method + w.path}><td>{w.method}</td><td><code>/webhook/{w.path}</code></td><td>{w.workflow_name}</td><td>{w.public}</td></tr>
          ))}
          {!status.webhooks.length && <tr><td colSpan={4} className="muted">No active webhook workflows.</td></tr>}
        </tbody>
      </table>
    </Modal>
  );
}
