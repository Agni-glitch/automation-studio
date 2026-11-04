"""Runs inside the sandbox subprocess. Reads a JSON job on stdin, runs the user code,
writes one marked JSON line to stdout. Must only use the standard library."""

import asyncio
import contextlib
import inspect
import io
import json
import linecache
import sys
import traceback

MARK = "__WF_RESULT__"
SCRIPT = "<workflow script>"


def main() -> None:
    real_stdout = sys.stdout
    job = json.loads(sys.stdin.read())
    for path in reversed(job.get("sys_path", [])):
        if path not in sys.path:
            sys.path.insert(0, path)

    code = job["code"]
    linecache.cache[SCRIPT] = (len(code), None, code.splitlines(True), SCRIPT)
    namespace = {
        "__name__": "__workflow__",
        "input": job.get("input"),
        "inputs": job.get("inputs", {}),
        "args": job.get("arguments", {}),
        "log": print,
    }
    captured = io.StringIO()
    try:
        with contextlib.redirect_stdout(captured):
            exec(compile(code, SCRIPT, "exec"), namespace)
            entry = namespace.get("main")
            if callable(entry):
                takes_input = len(inspect.signature(entry).parameters) > 0
                result = entry(namespace["input"]) if takes_input else entry()
                if inspect.iscoroutine(result):
                    result = asyncio.run(result)
            else:
                result = namespace.get("result")
        out = {"ok": True, "result": result}
    except BaseException as exc:  # noqa: BLE001 - report everything, including SystemExit
        frames = [f for f in traceback.extract_tb(exc.__traceback__) if f.filename == SCRIPT]
        out = {
            "ok": False,
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": "".join(traceback.format_list(frames)),
            },
        }
    out["logs"] = captured.getvalue().splitlines()
    try:
        line = json.dumps(out, default=str, ensure_ascii=False)
    except ValueError as exc:  # e.g. circular reference
        line = json.dumps({"ok": False, "logs": out["logs"],
                           "error": {"type": "SerializationError", "message": str(exc), "traceback": ""}})
    real_stdout.write("\n" + MARK + line + "\n")
    real_stdout.flush()


if __name__ == "__main__":
    main()
