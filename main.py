"""Command-line entry point.

    python main.py run examples/hello_workflow.json [--trigger JSON] [--no-db]
    python main.py run <workflow-id>                        # a workflow saved in the database
    python main.py cred set anthropic api_key               # prompts for each value (hidden)
    python main.py cred set smtp host port username password from_address --type smtp
    python main.py cred list | cred delete NAME
    python main.py wf import examples/webhook_hello.json --activate | wf list | wf activate ID | wf deactivate ID
    python main.py open                                     # desktop app (starts the service if needed)
    python main.py serve [-v] [--dev]                       # background service: GUI API + triggers + tunnel
    python main.py status | stop | autostart on|off|status | tunnel on|off|status
    python main.py history [--workflow ID] [--show EXECUTION_ID]

Data lives in %LOCALAPPDATA%\\AutomationEngine\\data.db unless --db is given.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import logging
import sys
from pathlib import Path

from engine import EventType, ExecutionEvent, ExecutionStatus, WorkflowEngine, WorkflowValidationError

_SECRET_HINTS = ("key", "token", "password", "secret")


CLI = "studio" if getattr(sys, "frozen", False) else "python main.py"


def print_event(event: ExecutionEvent) -> None:
    ts = event.timestamp.astimezone().strftime("%H:%M:%S.%f")[:-3]
    node = f"[{event.node_id}]" if event.node_id else ""
    p = event.payload
    match event.type:
        case EventType.NODE_SUCCEEDED:
            detail = f"-> {p['outputs']} in {p['duration_ms']:.0f} ms: {json.dumps(p['output'], ensure_ascii=False)[:110]}"
        case EventType.NODE_FAILED:
            detail = f"{p['error_type']}: {p['error']}" + (" (handled)" if p["handled"] else "")
        case EventType.NODE_SKIPPED:
            detail = p["reason"]
        case EventType.NODE_RETRY:
            detail = f"attempt {p['attempt']} failed ({p['error']}), retrying in {p['next_attempt_in_s']}s"
        case EventType.NODE_LOG:
            detail = f"{p['level'].upper()}: {p['message']}"
        case EventType.EXECUTION_FINISHED:
            detail = f"{p['status'].upper()} in {p['duration_ms']:.0f} ms" + (f" - {p['error']}" if p["error"] else "")
        case _:
            detail = ""
    print(f"{ts} {event.type.value:<19} {node:<14} {detail}")


def open_db(args: argparse.Namespace):
    from database import Database

    return Database(args.db) if args.db else Database.open_default()


async def cmd_run(args: argparse.Namespace) -> int:
    db = None if args.no_db else open_db(args)
    source = Path(args.workflow)
    if source.exists():
        workflow = source.read_text(encoding="utf-8-sig")  # tolerate Notepad/PowerShell BOMs
    elif db is not None and (saved := db.get_workflow(args.workflow)) is not None:
        workflow = saved
    else:
        print(f"no such file or saved workflow: {args.workflow}", file=sys.stderr)
        return 2

    kwargs = {"credentials": db} if db is not None else {}
    engine = WorkflowEngine(**kwargs)
    engine.events.subscribe(print_event)
    try:
        result = await engine.run(workflow, trigger_data=json.loads(args.trigger) if args.trigger else None)
    except WorkflowValidationError as exc:
        print("Workflow is invalid:\n  - " + "\n  - ".join(exc.errors), file=sys.stderr)
        return 2
    if db is not None:
        db.save_execution(result)
        print(f"\nsaved as execution {result.execution_id}")
        db.close()
    return 0 if result.status is ExecutionStatus.SUCCESS else 1


def cmd_cred(args: argparse.Namespace) -> int:
    with open_db(args) as db:
        if args.action == "list":
            for c in db.list_credentials():
                print(f"{c['name']:<24} {c['type']:<10} fields={','.join(c['fields'])}  updated={c['updated_at'][:19]}")
        elif args.action == "delete":
            print("deleted" if db.delete_credential(args.name) else "not found")
        else:
            data = {}
            for field in args.fields:
                prompt = f"{args.name}.{field}: "
                secret = any(h in field.lower() for h in _SECRET_HINTS)
                data[field] = getpass.getpass(prompt) if secret else input(prompt)
            db.set_credential(args.name, data, type=args.type)
            print(f"stored credential '{args.name}' ({len(data)} field(s), encrypted)")
    return 0


def _setup_logging(background: bool) -> None:
    from logging.handlers import RotatingFileHandler

    from backend import paths

    import os

    # pythonw / windowed .exe: no console streams. Give libraries somewhere harmless to write.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    handlers: list[logging.Handler] = []
    paths.LOG_DIR.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(paths.LOG_DIR / "service.log", maxBytes=2_000_000, backupCount=3,
                                       encoding="utf-8")
    file_handler.setFormatter(fmt)
    handlers.append(file_handler)
    if not background and sys.stderr is not None and getattr(sys.stderr, "name", "") != os.devnull:
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%H:%M:%S"))
        handlers.append(console)
    logging.basicConfig(level=logging.INFO, handlers=handlers, force=True)
    for noisy in ("httpx", "watchdog"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def cmd_serve(args: argparse.Namespace) -> int:
    from backend import paths
    from backend.service import AlreadyRunningError, InstanceLock, StudioService

    _setup_logging(args.background)
    lock = InstanceLock(paths.LOCK_FILE)
    try:
        lock.acquire()
    except AlreadyRunningError as exc:
        logging.error("%s", exc)
        return 3
    db = open_db(args)
    dev_origins = ("http://localhost:5173", "http://127.0.0.1:5173") if args.dev else ()
    tray = args.background if args.tray is None else args.tray
    service = StudioService(db, api_port=args.api_port, webhook_host=args.host, webhook_port=args.port,
                            dev_origins=dev_origins, poll_seconds=args.poll, tray=tray)
    if args.verbose:
        service.engine.events.subscribe(print_event)
    if args.host not in ("127.0.0.1", "localhost"):
        logging.warning("webhooks are reachable from the network on %s; protect them with auth: header", args.host)
    logging.info("data: %s  (Ctrl+C to stop)", db.path)
    try:
        await service.run_forever()
    finally:
        db.close()
        lock.release()
    return 0


def _service_request(method: str, path: str, body: dict | None = None) -> dict | None:
    """Call the running service's API (None if it isn't running)."""
    import httpx

    from backend import paths

    try:
        info = json.loads(paths.SERVICE_FILE.read_text(encoding="utf-8"))
        token = paths.TOKEN_FILE.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    try:
        resp = httpx.request(method, f"{info['api_url']}{path}", json=body,
                             headers={"X-Studio-Token": token}, timeout=30)
    except httpx.TransportError:
        return None
    resp.raise_for_status()
    return resp.json()


def cmd_status(args: argparse.Namespace) -> int:
    status = _service_request("GET", "/api/status")
    if status is None:
        print(f"service: not running  (start it with: {CLI} serve, or {CLI} open)")
        return 1
    print(f"service: running (pid {status['pid']}) since {status['started_at'][:19]}")
    print(f"GUI/API: {status['api_url']}")
    print(f"webhooks: {status['webhook_url']}")
    tunnel = status["tunnel"]
    print(f"tunnel:  {tunnel['state']}" + (f" -> {status['public_webhook_url']}" if tunnel["public_url"] else "")
          + (f"  ({tunnel['error']})" if tunnel["error"] and tunnel["state"] != "running" else ""))
    print(f"autostart at login: {'on' if status['autostart']['enabled'] else 'off'}")
    for wf in status["active_workflows"]:
        print(f"  ACTIVE {wf['name']}: " + ("; ".join(wf["triggers"]) or "no listening triggers"))
    for wf_id, err in status["trigger_errors"].items():
        print(f"  ERROR  {wf_id}: {err}")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    import time

    if _service_request("POST", "/api/shutdown") is None:
        print("service: not running")
        return 1
    for _ in range(40):  # wait for triggers/tunnel/executions to wind down
        time.sleep(0.25)
        if _service_request("GET", "/api/status") is None:
            print("service stopped")
            return 0
    print("service is still shutting down (waiting for running executions)")
    return 0


def cmd_autostart(args: argparse.Namespace) -> int:
    from backend import autostart

    result = {"on": autostart.enable, "off": autostart.disable, "status": autostart.status}[args.action]()
    print(f"autostart at login: {'on' if result['enabled'] else 'off'}")
    if result["enabled"]:
        print(f"  runs: {result['command']}")
        if not result.get("up_to_date", True):
            print("  warning: points at an old location; run 'autostart on' again")
    return 0


def cmd_tunnel(args: argparse.Namespace) -> int:
    if args.action == "status":
        result = _service_request("GET", "/api/tunnel")
    else:
        settings = {"enabled": args.action == "on", "mode": args.mode, "credential": args.credential,
                    "hostname": args.hostname}
        result = _service_request("PUT", "/api/tunnel", settings)
        if result is None:  # service not running: store the setting for next start
            with open_db(args) as db:
                db.set_setting("tunnel", settings)
            print(f"tunnel {args.action} (applies when the service starts)")
            return 0
    if result is None:
        print("service: not running")
        return 1
    st = result["status"]
    print(f"tunnel: {st['state']} ({st['mode'] or result['settings']['mode']})")
    if st["public_url"]:
        print(f"  public webhook base: {st['webhook_base']}")
    elif args.action == "on":
        print(f"  starting... run '{CLI} tunnel status' in a few seconds for the URL")
    if st["error"] and st["state"] != "running":
        print(f"  {st['error']}")
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    path = {"status": ("GET", "/api/status"), "check": ("POST", "/api/updates/check"),
            "install": ("POST", "/api/updates/install")}[args.action]
    try:
        result = _service_request(*path)
    except Exception as exc:  # e.g. 400 when install is refused
        detail = getattr(getattr(exc, "response", None), "text", "") or str(exc)
        print(f"update {args.action} failed: {detail}")
        return 1
    if result is None:
        print("service: not running")
        return 1
    if args.action == "install":
        print(f"installing {result['installing']}; the app restarts when done")
        return 0
    u = result["updates"] if args.action == "status" else result
    print(f"current {u['current_version']}  source {u['source'] or '(none)'}")
    if u["error"]:
        print(f"  {u['error']}")
    elif u["available"]:
        print(f"  update available: {u['latest']['version']}"
              + ("" if u["can_auto_install"] else f"  ({u['auto_install_blocked_reason']})"))
    elif u["checked_at"]:
        print("  up to date")
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    from desktop.app_window import main as open_window

    return open_window()


def cmd_wf(args: argparse.Namespace) -> int:
    with open_db(args) as db:
        if args.action == "list":
            for w in db.list_workflows():
                state = "ACTIVE" if w["active"] else "      "
                print(f"{state} {w['id']:<34} {w['name']:<32} updated={w['updated_at'][:19]}")
        elif args.action in ("activate", "deactivate"):
            found = db.set_workflow_active(args.id, args.action == "activate")
            print(f"{args.action}d {args.id}" if found else f"no saved workflow {args.id}")
            return 0 if found else 1
        else:
            engine = WorkflowEngine()
            try:
                workflow = engine.parse(Path(args.file).read_text(encoding="utf-8-sig"))
                engine.validate(workflow)
            except WorkflowValidationError as exc:
                print("Workflow is invalid:\n  - " + "\n  - ".join(exc.errors), file=sys.stderr)
                return 2
            db.save_workflow(workflow, active=True if args.activate else None)
            print(f"imported '{workflow.name}' as {workflow.id}" + (" (active)" if args.activate else ""))
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    with open_db(args) as db:
        if args.show:
            result = db.get_execution(args.show)
            if result is None:
                print("not found")
                return 1
            print(result.model_dump_json(indent=2))
            return 0
        for e in db.list_executions(args.workflow, args.limit):
            print(f"{e['started_at'][:19]}  {e['status']:<9} {e['workflow_name']:<28} {e['id']}  {e['error'] or ''}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", help="database path (default: %%LOCALAPPDATA%%\\AutomationEngine\\data.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a workflow file or saved workflow id")
    run.add_argument("workflow")
    run.add_argument("--trigger", help="JSON trigger payload")
    run.add_argument("--no-db", action="store_true", help="don't use the database (no credentials, no history)")

    cred = sub.add_parser("cred", help="manage encrypted credentials")
    cred_sub = cred.add_subparsers(dest="action", required=True)
    cred_set = cred_sub.add_parser("set", help="create/replace a credential; prompts for each field")
    cred_set.add_argument("name")
    cred_set.add_argument("fields", nargs="+", help="field names, e.g. api_key")
    cred_set.add_argument("--type", default="generic")
    cred_sub.add_parser("list")
    cred_del = cred_sub.add_parser("delete")
    cred_del.add_argument("name")

    wf = sub.add_parser("wf", help="manage saved workflows")
    wf_sub = wf.add_subparsers(dest="action", required=True)
    wf_imp = wf_sub.add_parser("import", help="save (or update) a workflow file in the database")
    wf_imp.add_argument("file")
    wf_imp.add_argument("--activate", action="store_true", help="also turn its triggers on")
    wf_sub.add_parser("list")
    for action in ("activate", "deactivate"):
        sub_cmd = wf_sub.add_parser(action, help=f"{action} a saved workflow's triggers")
        sub_cmd.add_argument("id")

    serve = sub.add_parser("serve", help="run the background service: GUI API + triggers + tunnel")
    serve.add_argument("--host", default="127.0.0.1", help="webhook listen address")
    serve.add_argument("--port", type=int, default=5678, help="webhook port")
    serve.add_argument("--api-port", type=int, default=5680, help="GUI/API port (always 127.0.0.1)")
    serve.add_argument("--poll", type=float, default=3.0, help="seconds between database checks")
    serve.add_argument("--background", action="store_true", help="log to file only (used by autostart)")
    serve.add_argument("--dev", action="store_true", help="allow the Vite dev server (port 5173) to connect")
    serve.add_argument("--tray", dest="tray", action="store_true", default=None,
                       help="show the system-tray icon (default: on with --background)")
    serve.add_argument("--no-tray", dest="tray", action="store_false")
    serve.add_argument("-v", "--verbose", action="store_true", help="print every execution event")

    sub.add_parser("status", help="show the running service's state")
    sub.add_parser("stop", help="stop the background service")
    sub.add_parser("open", help="open the desktop app (starts the service if needed)")

    upd = sub.add_parser("update", help="check for / install app updates")
    upd.add_argument("action", choices=["status", "check", "install"])

    auto = sub.add_parser("autostart", help="start the service at Windows login")
    auto.add_argument("action", choices=["on", "off", "status"])

    tun = sub.add_parser("tunnel", help="public HTTPS URL for webhooks via Cloudflare Tunnel")
    tun.add_argument("action", choices=["on", "off", "status"])
    tun.add_argument("--mode", choices=["quick", "token"], default="quick",
                     help="quick: random trycloudflare.com URL, no account; token: your named tunnel")
    tun.add_argument("--credential", help="token mode: credential holding the tunnel 'token'")
    tun.add_argument("--hostname", help="token mode: the public hostname routed to this tunnel")

    hist = sub.add_parser("history", help="list past executions")
    hist.add_argument("--workflow")
    hist.add_argument("--limit", type=int, default=20)
    hist.add_argument("--show", metavar="EXECUTION_ID")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "run":
        return asyncio.run(cmd_run(args))
    if args.command == "serve":
        try:
            return asyncio.run(cmd_serve(args))
        except KeyboardInterrupt:
            print("stopped")
            return 0
    return {"cred": cmd_cred, "wf": cmd_wf, "history": cmd_history, "status": cmd_status,
            "autostart": cmd_autostart, "tunnel": cmd_tunnel, "open": cmd_open,
            "stop": cmd_stop, "update": cmd_update}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
