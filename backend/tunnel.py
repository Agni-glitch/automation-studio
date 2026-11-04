"""Cloudflare Tunnel: expose the local webhook server on a public HTTPS URL.

Two modes:
* quick  - no account. A random https://<words>.trycloudflare.com URL that changes every
           time the tunnel restarts. Good for testing and occasional use.
* token  - a named tunnel from the Cloudflare dashboard (free account + your domain):
           stable hostname. Store the tunnel token as a credential with a 'token' field and
           set the public hostname you configured for it.

Only the webhook port is exposed, never the Studio API. ``cloudflared.exe`` is downloaded
from Cloudflare's official GitHub releases on first use.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import subprocess
import sys
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

import httpx

logger = logging.getLogger(__name__)

DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
_QUICK_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
_CONNECTED = re.compile(r"Registered tunnel connection", re.I)
State = Literal["stopped", "downloading", "starting", "running", "reconnecting", "error"]


class TunnelError(Exception):
    pass


class TunnelManager:
    def __init__(
        self,
        bin_dir: Path,
        target_url: Callable[[], str],
        get_credential: Callable[[str], Any] | None = None,
        on_change: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.binary = bin_dir / "cloudflared.exe"
        self._target_url = target_url
        self._get_credential = get_credential
        self._on_change = on_change
        self.state: State = "stopped"
        self.mode: str | None = None
        self.public_url: str | None = None
        self.error: str | None = None
        self.log: deque[str] = deque(maxlen=200)
        self._task: asyncio.Task[None] | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._config: dict[str, Any] = {}

    # ---- public API

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "mode": self.mode,
            "public_url": self.public_url,
            "webhook_base": f"{self.public_url}/webhook/" if self.public_url else None,
            "error": self.error,
            "installed": self.binary.exists(),
            "recent_log": list(self.log)[-15:],
        }

    @property
    def config(self) -> dict[str, Any]:
        return dict(self._config)

    async def start(self, mode: str = "quick", credential: str | None = None, hostname: str | None = None) -> None:
        if mode not in ("quick", "token"):
            raise TunnelError("mode must be 'quick' or 'token'")
        if mode == "token" and not (credential and hostname):
            raise TunnelError("token mode needs a credential (with 'token') and the public hostname")
        await self.stop()
        self._config = {"mode": mode, "credential": credential, "hostname": hostname}
        self.mode, self.error, self.public_url = mode, None, None
        self._task = asyncio.create_task(self._supervise(), name="cloudflared")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._config = {}
        self.mode = self.public_url = None
        self._set("stopped")

    async def ensure_binary(self) -> Path:
        if self.binary.exists():
            return self.binary
        self._set("downloading")
        self.binary.parent.mkdir(parents=True, exist_ok=True)
        part = self.binary.with_name("cloudflared.download.exe")
        logger.info("downloading cloudflared from %s", DOWNLOAD_URL)
        async with httpx.AsyncClient(follow_redirects=True, timeout=120) as client:
            async with client.stream("GET", DOWNLOAD_URL) as resp:
                if resp.status_code != 200:
                    raise TunnelError(f"cloudflared download failed: HTTP {resp.status_code}")
                with open(part, "wb") as f:
                    async for chunk in resp.aiter_bytes(1 << 16):
                        f.write(chunk)
        version = await _run([str(part), "--version"])
        if "cloudflared version" not in version:
            part.unlink(missing_ok=True)
            raise TunnelError(f"downloaded file is not cloudflared: {version[:200]!r}")
        # Antivirus usually scans (and briefly locks) a freshly downloaded .exe.
        for attempt in range(30):
            try:
                os.replace(part, self.binary)
                break
            except PermissionError:
                if attempt == 29:
                    raise TunnelError(f"cannot move {part.name} into place (locked by another program)") from None
                await asyncio.sleep(0.5)
        logger.info("installed %s", version.strip())
        return self.binary

    # ---- internals

    def _set(self, state: State, error: str | None = None) -> None:
        self.state = state
        if error is not None:
            self.error = error
        if self._on_change is not None:
            with contextlib.suppress(Exception):
                self._on_change(self.status())

    async def _command(self) -> tuple[list[str], dict[str, str]]:
        env = dict(os.environ)
        base = [str(self.binary), "tunnel", "--no-autoupdate"]
        if self._config["mode"] == "quick":
            return [*base, "--url", self._target_url()], env
        if self._get_credential is None:
            raise TunnelError("no credential store available")
        cred = await self._get_credential(self._config["credential"])
        if not cred.get("token"):
            raise TunnelError(f"credential '{self._config['credential']}' has no 'token' field")
        env["TUNNEL_TOKEN"] = str(cred["token"])  # env, not argv: keeps it out of process listings
        return [*base, "run"], env

    async def _supervise(self) -> None:
        backoff = 2.0
        try:
            await self.ensure_binary()
            while True:
                self._set("starting" if self.state != "reconnecting" else "reconnecting")
                cmd, env = await self._command()
                await self._run_once(cmd, env)
                # process exited on its own
                self.public_url = None
                self._set("reconnecting", error=self.error or "cloudflared exited; restarting")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # download/config problems: don't retry forever
            logger.error("tunnel failed: %s", exc)
            self.public_url = None
            self._set("error", error=str(exc))

    async def _run_once(self, cmd: list[str], env: dict[str, str]) -> None:
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        proc = await asyncio.create_subprocess_exec(
            *cmd, env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            creationflags=flags,
        )
        self._proc = proc
        job = None
        if sys.platform == "win32":
            from engine.sandbox.runner import confine_process, release_job

            job = confine_process(proc.pid)  # dies with us, even on a hard crash
        try:
            assert proc.stderr is not None
            while line_bytes := await proc.stderr.readline():
                line = line_bytes.decode("utf-8", errors="replace").rstrip()
                self.log.append(line)
                if self._config["mode"] == "quick" and (m := _QUICK_URL.search(line)) and not self.public_url:
                    self.public_url = m.group(0)
                elif self._config["mode"] == "token" and _CONNECTED.search(line) and not self.public_url:
                    self.public_url = f"https://{self._config['hostname'].removeprefix('https://').strip('/')}"
                if self.public_url and self.state != "running" and (_CONNECTED.search(line) or "trycloudflare" in line):
                    self.error = None
                    self._set("running")
                    logger.info("tunnel up: %s -> %s", self.public_url, self._target_url())
                if " ERR " in line or line.startswith("ERR"):
                    self.error = line[-300:]
            await proc.wait()
        finally:
            if proc.returncode is None:
                proc.kill()
                with contextlib.suppress(Exception):
                    await proc.wait()
            if job is not None:
                release_job(job)
            self._proc = None


async def _run(cmd: list[str]) -> str:
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, creationflags=flags)
    out, _ = await asyncio.wait_for(proc.communicate(), 30)
    return out.decode("utf-8", errors="replace")
