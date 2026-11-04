# Architecture

Automation Studio is one Python program with a React editor. When packaged, it is a single
folder with two executables: `AutomationStudio.exe` (the window) and `studio.exe` (the command
line).

```
 ┌──────────────────────┐   REST + WebSocket    ┌────────────────────────────────────┐
 │ Desktop window       │  127.0.0.1:5680       │ Background service (backend/)      │
 │ PyWebView + React UI │ ────────────────────▶ │  FastAPI API, tray icon, updater   │
 └──────────────────────┘   token required      │  TriggerManager ─┐                 │
                                                │  WorkflowEngine ◀┘  (engine/)      │
   webhooks ──▶ 127.0.0.1:5678 ───────────────▶ │  SQLite + encrypted vault          │
   (optionally via Cloudflare Tunnel)           │  (database/)                       │
                                                └────────────────────────────────────┘
```

The window is only a client: closing it leaves the service, and every active workflow,
running. The service is a single instance per user, enforced by a lock file.

## Repository layout

```
engine/                  workflow engine, usable on its own
├── core.py              WorkflowEngine, graph validation, scheduler, retries, cancellation
├── models.py            Pydantic models: WorkflowDefinition, NodeDefinition, ExecutionResult
├── expressions.py       {{ path }} templating: lookups only, no eval
├── events.py            ordered event bus feeding logs and the live editor
├── errors.py            retryable vs non-retryable errors
├── nodes/               one module per node family; registry.py maps type -> class
├── llm/                 Anthropic, OpenAI and Ollama over plain REST (httpx)
├── sandbox/             Python Script runner: subprocess in a Windows Job Object
└── triggers/            TriggerManager, webhook server, folder watcher, schedules, cron parser
database/
├── db.py                SQLite (WAL): workflows, executions, credentials, settings, migrations
└── vault.py             Fernet encryption; master key protected by Windows DPAPI
backend/                 the background service
├── service.py           API + triggers + tunnel + tray in one process
├── server.py            REST API, /ws/logs WebSocket, serves the editor
├── tunnel.py            downloads and supervises cloudflared
├── autostart.py         start at sign-in (HKCU Run key, no admin)
├── tray.py, icon.py     tray icon and the app icon (drawn in code)
├── updates.py           update checks and verified self-install
└── paths.py             data and resource locations, source vs packaged
desktop/app_window.py    PyWebView window; starts the service if needed
frontend/src/            React 18 + React Flow 12 + CodeMirror (Vite, TypeScript)
main.py, app.py          CLI entry point; packaged entry point (no args opens the window)
build/                   packaging: PyInstaller spec, Inno Setup script, signing, release
examples/                importable workflows
tests/                   pytest suite
```

## The engine

`WorkflowEngine.start()` validates the graph (no cycles, known node types, valid parameters),
then schedules nodes dynamically: a node starts when all its predecessors are done, and
independent branches run concurrently up to `max_concurrency`. Branching works through output
ports, so a node whose incoming ports didn't fire is skipped. Each node run gets a `NodeContext`
with its input, logging, credentials and `run_blocking()` for synchronous libraries. Every step
is published on the event bus, which feeds the log drawer, the live node colors and the run
history. See [How a workflow runs](nodes.md#how-a-workflow-runs) for the exact rules.

## Design decisions

- **No LangChain.** The AI Agent node calls Anthropic, OpenAI and Ollama directly over `httpx`
  behind one small provider interface. That keeps one HTTP stack, makes everything easy to mock
  in tests, and keeps the app small. Structured output uses each API's native mechanism (a forced
  tool call, `json_schema` and `format` respectively) and is validated again locally.
- **The Python sandbox is a separate process**, never `exec()` inside the service. It runs inside
  a Windows Job Object with a memory cap and a one-process limit, and is killed with the job. It
  gets a stripped environment, a temporary folder and a timeout. This protects the service from
  crashes and runaway scripts, but it is **not** an isolation boundary: scripts can still use the
  network and read files.
- **Credentials** are encrypted with Fernet; the master key is encrypted with Windows DPAPI for
  the current user. There is no master password, and a copied database can't be decrypted on
  another machine or account.
- **Triggers** use FastAPI and uvicorn for webhooks (the same stack as the API) and `watchdog` for
  folders. Schedules use a small built-in cron parser that re-checks the wall clock every 30
  seconds, so it stays correct across sleep and daylight-saving changes.
- **Packaging** bundles the official embeddable CPython, so Python Script nodes work on PCs
  without Python installed.

## Security model

The API can run code, so it is locked down:

- It listens on `127.0.0.1` only.
- Every request needs the per-install token (`X-Studio-Token`). The token is injected into the
  page the service serves, so only the app's own window has it.
- Requests with a foreign `Host` header are rejected, which blocks DNS-rebinding attacks from
  websites. The WebSocket also checks `Origin`, and pages refuse to be framed.
- Credential values are redacted from logs, errors and history.

Report vulnerabilities as described in [SECURITY.md](../SECURITY.md).

## Public webhooks

`studio tunnel on` (or the switch in Settings) downloads `cloudflared.exe` from Cloudflare's
GitHub releases into `%LOCALAPPDATA%\AutomationEngine\bin` and opens a **quick tunnel**: a random
`https://<words>.trycloudflare.com` URL that needs no account and changes on every restart.

Only the webhook port is exposed, never the API. Calls that arrive through the tunnel are refused
with 403 unless the webhook uses token auth or sets `allow_public`.

### Stable tunnel URL

For a permanent address you need a free Cloudflare account and a domain on Cloudflare:

1. In the Cloudflare dashboard, create a tunnel under **Zero Trust → Networks → Tunnels** and
   route a public hostname (for example `hooks.example.com`) to `http://localhost:5678`.
2. Save the tunnel's token as a credential: `studio cred set cf-tunnel token`.
3. Run `studio tunnel on --mode token --credential cf-tunnel --hostname hooks.example.com`.
