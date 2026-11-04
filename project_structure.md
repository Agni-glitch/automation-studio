# Project structure

`[x]` = implemented and tested, `[ ]` = planned.

```
AutomationSoftware/
├── main.py                      [x] CLI: run, serve, cred, wf, history
├── demo_job_pipeline.py         [x] Fetch jobs -> clean -> AI CV match -> If -> Email (offline or --live)
├── pyproject.toml               [x] deps + pytest config
├── examples/
│   ├── hello_workflow.json      [x] trigger -> parallel branches -> If routing
│   ├── job_pipeline.json        [x] the end-to-end job matching workflow
│   ├── webhook_hello.json       [x] webhook (wait mode) -> If -> reply; no keys needed
│   └── cv_inbox.json            [x] folder watcher -> read CV -> AI profile -> write .analysis.json
├── engine/
│   ├── __init__.py              [x] public API
│   ├── core.py                  [x] WorkflowEngine, WorkflowGraph, scheduler, retries, cancellation
│   ├── models.py                [x] WorkflowDefinition / NodeDefinition / ExecutionResult (Pydantic)
│   ├── expressions.py           [x] safe {{ path }} templating (no eval)
│   ├── events.py                [x] EventBus + ordered execution events (logs/GUI feed)
│   ├── errors.py                [x] exception hierarchy (retryable vs non-retryable)
│   ├── nodes/
│   │   ├── base.py              [x] BaseNode, NodeContext, NodeResult
│   │   ├── registry.py          [x] type string -> class, GUI catalog
│   │   ├── triggers.py          [x] trigger.manual / .webhook / .file / .schedule (node side)
│   │   ├── logic.py             [x] Set, If, Wait
│   │   ├── _http.py             [x] shared/injectable httpx client
│   │   ├── http_request.py      [x] action.http_request (bearer / api-key header|query / basic auth)
│   │   ├── ai_agent.py          [x] ai.agent (Anthropic / OpenAI / Ollama, JSON-schema output)
│   │   ├── python_script.py     [x] code.python (sandboxed subprocess)
│   │   ├── email.py             [x] action.email (SMTP, dry_run)
│   │   ├── social.py            [x] action.social_post (LinkedIn Posts API, dry_run default)
│   │   ├── browser.py           [x] action.browser (Playwright; installed Edge by default)
│   │   └── desktop.py           [x] action.desktop (PyAutoGUI; one at a time, fail-safe on)
│   ├── llm/                     [x] base.py + anthropic.py, openai.py, ollama.py (plain REST via httpx)
│   ├── sandbox/                 [x] runner.py (Job Object limits) + _bootstrap.py (child side)
│   └── triggers/
│       ├── manager.py           [x] TriggerManager: activate / deactivate / sync / fire
│       ├── webhook.py           [x] one local FastAPI+uvicorn server, /webhook/<path>
│       ├── file_watch.py        [x] watchdog listener with write-settling
│       ├── schedule.py          [x] cron + interval, sleep/DST-safe
│       └── cron.py              [x] 5-field cron parser
├── database/
│   ├── db.py                    [x] SQLite (WAL): workflows, executions, credentials, migrations
│   └── vault.py                 [x] Fernet encryption, master key protected by Windows DPAPI
├── backend/                     [x] Phase 2: the background service
│   ├── server.py                [x] FastAPI: /api/* REST + /ws/logs WebSocket + serves the SPA
│   ├── service.py               [x] one process: API + triggers + tunnel, single-instance lock
│   ├── tunnel.py                [x] Cloudflare Tunnel (auto-downloads cloudflared, supervises it)
│   ├── autostart.py             [x] start at Windows login (HKCU Run key, no admin)
│   ├── tray.py                  [x] system-tray icon: status dot, quick toggles, failure notifications
│   ├── updates.py               [x] update checks (GitHub releases / manifest) + verified self-install
│   ├── icon.py                  [x] app icon drawn in code (tray + build share it)
│   └── paths.py                 [x] data/resource paths (source checkout or PyInstaller build)
├── desktop/
│   └── app_window.py            [x] PyWebView window; starts the service if needed
├── frontend/                    [x] React 18 + React Flow 12 + CodeMirror (Vite, TypeScript)
│   └── src/
│       ├── App.tsx              canvas state, run/save/activate, live status painting
│       ├── api.ts               token-authenticated REST client + reconnecting WebSocket
│       ├── graph.ts             workflow JSON <-> React Flow nodes/edges, auto-layout
│       └── components/          StudioNode, Palette, Inspector, SchemaForm, Editors, LogDrawer, Dialogs
├── app.py                       [x] packaged entry point (no args -> window, otherwise CLI)
├── build_windows.bat            [x] one-click build: venv deps -> build/package.py
├── build/
│   ├── package.py               [x] frontend -> embeddable Python -> PyInstaller -> Inno Setup
│   ├── AutomationStudio.spec    [x] one folder, two exes: AutomationStudio.exe (windowed) + studio.exe (console)
│   ├── installer.iss            [x] per-user installer: shortcuts, optional autostart, clean uninstall
│   ├── sign.ps1                 [x] Authenticode signing (cert store / .pfx / custom command)
│   ├── make_icon.py             [x] generates assets/app.ico
│   ├── cache/                   downloaded embeddable Python (reused between builds)
│   └── output/                  dist/AutomationStudio/ and AutomationStudio-Setup-<version>.exe
└── tests/
    ├── test_core.py             [x] engine (13)
    ├── test_nodes.py            [x] nodes incl. real sandbox limits (16)
    ├── test_db.py               [x] storage + encryption + DPAPI (5)
    ├── test_triggers.py         [x] cron, live webhook server, real folder watching, schedules (19)
    ├── test_automation.py       [x] real Edge browser run; desktop with a fake PyAutoGUI (5)
    ├── test_server.py           [x] API auth/host guard, WS origin check, run + live events, SPA (8)
    └── test_updates.py          [x] release parsing, SHA-256 / signer verification, refusals, API (6)
```

## Running the app

```
cd frontend && npm install && npm run build && cd ..    # once, and after UI changes
python main.py open        # desktop window (starts the background service if needed)
python main.py status      # service, tunnel, autostart, active workflows
python main.py stop
python main.py autostart on|off        # start the service at Windows login
python main.py tunnel on|off|status    # public HTTPS URL for webhooks
```
UI development with hot reload: `python main.py serve --dev` in one terminal, `npm run dev` in
`frontend/`, then open http://localhost:5173.

The GUI is a client of the service: closing the window keeps active workflows running.
Logs: `%LOCALAPPDATA%\AutomationEngine\logs\service.log`.

## Building the Windows app

```
build_windows.bat                       # or: python build/package.py [--skip-frontend] [--no-installer]
```
Needs Node.js 20+ and Inno Setup 6 (`winget install JRSoftware.InnoSetup --scope user`).
Output (about 2 minutes):

* `build/output/dist/AutomationStudio/`: portable program folder (about 210 MB)
  * `AutomationStudio.exe`: double-click for the app; `serve --background` runs the service
  * `studio.exe`: CLI (`studio status`, `studio stop`, `studio tunnel on`, ...)
  * `_internal/python/`: official embeddable CPython that runs Python Script nodes
    (standard library only; scripts can't `pip install` into it)
* `build/output/AutomationStudio-Setup-<version>.exe`: installer (about 76 MB). It installs
  per-user into `%LOCALAPPDATA%\Programs\AutomationStudio` with no admin prompt. Options:
  desktop shortcut and start-at-sign-in. It stops a running service before upgrading or
  uninstalling. Uninstall keeps user data in `%LOCALAPPDATA%\AutomationEngine`.

Browser automation in the packaged app uses the installed Edge (or Chrome). The
`chromium` / `firefox` / `webkit` options aren't available there, because their browser
downloads aren't bundled.

### Code signing
Unsigned builds trigger SmartScreen's "Windows protected your PC" on other machines. Once you
have a certificate, set one variable and build. Both exes, the installer and the uninstaller
get signed and timestamped:

```
set STUDIO_SIGN_THUMBPRINT=<thumbprint>        & rem cert in your Windows store (incl. USB-token/EV certs)
rem   or STUDIO_SIGN_PFX=<file.pfx> + STUDIO_SIGN_PFX_PASSWORD=<password>
rem   or STUDIO_SIGN_COMMAND=<any signer command, {file} = path>   (Azure Trusted Signing, SignPath, ...)
build_windows.bat --sign                       & rem --sign fails loudly if nothing is configured
```
Where certificates come from: a public CA (an OV/EV code-signing certificate, usually on a
hardware token or cloud HSM), Microsoft's Azure Trusted Signing (a managed signing service),
or SignPath (free for open-source projects). SmartScreen trust also builds up per certificate
over downloads; EV certificates start with more of it.

### Tray icon
The background service shows a tray icon. The dot is green when OK, amber when an update is
available, and red for trigger or tunnel errors. Its menu has: open the app, the public URL
(with copy), and toggles for the tunnel and start-at-sign-in, plus updates, logs, and Quit
(stops background workflows). Failed background runs show a Windows notification, at most one
every 20 s. `serve --tray/--no-tray` overrides the default (on with `--background`).

### Updates
Settings → Updates takes `github:owner/repo` (latest GitHub release with a `*Setup*.exe` asset)
or an `https://` URL to a `latest.json` manifest. Every build writes `build/output/latest.json`
with the installer's SHA-256; fill in its `url` and host both files. To bake a default into
builds: `build/package.py --update-source github:you/repo`. The app checks daily and shows an
"↑ vX" pill. **Install update** downloads the installer, then:
* signed app: requires a valid signature from the same certificate;
* unsigned app: requires the published SHA-256 to match (GitHub provides asset digests).

If neither check is possible it refuses, and you can use the release page instead. The update
runs the installer silently, which stops the service, upgrades, and reopens the app. In-app
install only works in the packaged app; from source, `git pull` and rebuild.

### API security
The API can run code, so it only listens on 127.0.0.1 and rejects any request without the
per-install token (`X-Studio-Token`, embedded in the served page) or with a foreign `Host`
header (DNS rebinding). The WebSocket also checks `Origin`. Pages refuse to be framed.

### Public webhooks
`tunnel on` downloads `cloudflared.exe` from Cloudflare's GitHub releases into
`%LOCALAPPDATA%\AutomationEngine\bin` and opens a quick tunnel: a random
`https://<words>.trycloudflare.com` URL with no account, which changes on every restart. For a
stable URL, create a named tunnel in the Cloudflare dashboard (free account and your own
domain), store its token as a credential, and run
`tunnel on --mode token --credential <name> --hostname hooks.example.com`.
Only the webhook port is exposed. Calls arriving through the tunnel are refused (403) unless
the webhook uses token auth or sets `allow_public: true`.

## Running in the background

```
python main.py wf import examples/webhook_hello.json --activate
python main.py serve            # Ctrl+C to stop; picks up imports/activations/edits within 3 s
```
Every triggered execution is saved to history (`python main.py history`).

| Trigger | Fires on | Output |
|---|---|---|
| `trigger.webhook` | `METHOD http://127.0.0.1:5678/webhook/<path>`; `response_mode: wait` replies with the workflow's output | `{method, path, query, headers, body, client}` |
| `trigger.file` | new/changed/deleted/renamed files matching `patterns`, after the file stops growing; temp/partial files ignored; rename-into-place counts as created | `{event, path, name, stem, extension, directory, size}` |
| `trigger.schedule` | `cron` (local time) or `every_seconds`; `skip_if_running` prevents overlap; missed runs while stopped are not replayed | `{scheduled_for, fired_at}` |

Trigger settings may use `{{ vars.x }}` (e.g. a folder path). Webhooks only listen on localhost
unless `serve --host` says otherwise; use `auth: header` + a `{token}` credential for anything exposed.

## Node reference

| Type | Credential fields | Notes |
|---|---|---|
| `action.http_request` | `token` / `api_key` / `username`+`password` | 429/5xx/network errors retry; other 4xx fail at once. Output `{status, headers, data}`. |
| `ai.agent` | `api_key` (optional for Ollama) | `output_schema` gives validated JSON in `result`. Schema mismatch is retryable. `base_url` for OpenAI-compatible servers. |
| `code.python` | none | Uses `input`, `inputs`, `args`, `print`/`log`. Define `main(input)` or set `result`. Limits: timeout, memory, no child processes, stripped env vars. |
| `action.email` | `host`, `port`, `username`, `password`, `security`, `from_address` | Gmail: `smtp.gmail.com`, 587, `starttls`, app password. |
| `action.social_post` | `access_token`, `author_urn` | `dry_run` defaults to true. `api_version` must be a currently supported LinkedIn version. |
| `action.browser` | none | Steps: goto, click, fill, type, press, select, check, hover, wait_for, wait, extract_text / _all_text / _html / _attribute, screenshot, evaluate. `profile_dir` keeps logins. |
| `action.desktop` | none | Steps: open, activate_window, hotkey, press, type (ASCII), paste (any text), click / double / right (x,y or image), move, scroll, screenshot, locate_image. Needs an unlocked desktop session. |

## Workflow JSON format

```json
{
  "name": "Job screening",
  "variables": { "threshold": 70 },
  "settings": { "max_concurrency": 4, "timeout_seconds": 600, "fail_fast": true },
  "nodes": [
    { "id": "fetch", "type": "action.http_request",
      "parameters": { "url": "https://api.example.com/jobs" },
      "credentials": { "default": "jobs-api-key" },
      "retry": { "max_attempts": 3, "backoff_seconds": 2 },
      "timeout_seconds": 30, "on_error": "stop" },
    { "id": "check", "type": "logic.if",
      "parameters": { "left": "{{ nodes.fetch.count }}", "operator": "greater_than", "right": 0 } }
  ],
  "connections": [
    { "source": "fetch", "target": "check" },
    { "source": "check", "target": "notify", "source_output": "true" }
  ]
}
```

## Execution semantics

| Topic | Behaviour |
|---|---|
| Scheduling | A node starts as soon as **all** its predecessors finish. Independent branches run in parallel, capped by `max_concurrency`. |
| Branching | Nodes declare output ports (`If` has `true`/`false`). A node runs only if at least one incoming connection's port fired; otherwise it is `skipped` and so is everything downstream. |
| Input | Root nodes get `trigger_data`. One upstream → `ctx.input` is its output. Several → `ctx.input` is `{node_id: output}`. |
| Expressions | `{{ input.x }}`, `{{ nodes.<id>.field[0] }}`, `{{ trigger.x }}`, `{{ vars.x }}`, `{{ execution.id }}`. Path lookup only, no code. A missing path is an error; `{{ input.x ?? "default" }}` marks it optional. Only **upstream** nodes are visible, so results never depend on timing. |
| Retries | `retry.max_attempts` with exponential backoff. `NonRetryableError` (bad params, missing credential, bad expression) fails immediately. |
| Errors | `on_error`: `stop` (fails the workflow), `continue` (`{"error":…}` on `main`), `error_output` (`{"error":…}` on the `error` port). |
| Fail fast | `fail_fast: true` cancels running branches on the first unhandled failure; `false` lets independent branches finish. |
| Timeouts | Per node (`timeout_seconds`, default 300) and per workflow. Blocking code must go through `ctx.run_blocking()` or timeouts can't interrupt it. |
| Triggers | `start(..., start_node="t2")` skips the other root triggers. |
| Secrets | Values returned by `ctx.get_credential()` are replaced with `***` in logs and error messages. |
| Cancel | `engine.cancel(execution_id)` or `handle.cancel()`. |

## Stack decisions (adjusted from the brief)

- **No LangChain; direct REST calls over `httpx`** for Anthropic, OpenAI and Ollama behind one small `LLMProvider` interface. One HTTP stack, trivially mockable, small `.exe`. Structured output: Anthropic = forced tool call, OpenAI = `json_schema` response format, Ollama = `format` schema; all re-validated locally.
- **Python sandbox = a separate subprocess**, not `exec()` in the engine process. It runs the real interpreter (not the venv launcher) inside a Windows Job Object: memory cap, one-process limit (no child processes), killed with the job. It also gets a stripped environment, a temp working dir and a timeout. This protects the engine from crashes and runaway scripts but is **not** a security boundary against malicious code (network and file access remain). Only run your own scripts. When packaged as `.exe`, ship a Python interpreter and pass it via `services={"python_executable": ...}`.
- **Credential vault:** Fernet (`cryptography`) with the master key encrypted by Windows DPAPI for the current user (`data.key` beside `data.db`). No master password, and the files are useless on another machine or account. Downside: a lost Windows profile means re-entering credentials.
- **Triggers:** FastAPI + uvicorn for webhooks (the same stack will serve the Phase 2 GUI API) and `watchdog` for folders. Scheduling uses a small built-in cron parser instead of APScheduler: fewer moving parts, and wall-clock re-checks every 30 s keep it correct across laptop sleep and DST changes.

## Writing a node

```python
from pydantic import BaseModel
from engine import BaseNode, NodeContext, register_node

@register_node
class UppercaseNode(BaseNode):
    type = "logic.uppercase"
    display_name = "Uppercase"
    category = "logic"

    class Parameters(BaseModel):
        text: str

    async def execute(self, ctx: NodeContext, params: Parameters):
        ctx.info(f"uppercasing {len(params.text)} chars")
        return {"text": params.text.upper()}
```
