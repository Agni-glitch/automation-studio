"""Update checks and verified self-update.

Update source (setting ``updates.source``, default baked in at build time):
* ``github:owner/repo``: the latest GitHub release; its ``*Setup*.exe`` asset is the installer
  (GitHub's published SHA-256 asset digest is used when present);
* ``https://.../latest.json``: a manifest
  ``{"version": "0.3.0", "url": "https://.../Setup.exe", "sha256": "...", "notes": "...", "page": "..."}``.

An installer is only run if it can be authenticated:
* when the running app is code-signed, the download must carry a *valid* signature from the
  same certificate; otherwise
* its SHA-256 must match the digest published with the release.
If neither holds, auto-install is refused and the user gets the download page instead.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from . import paths

logger = logging.getLogger(__name__)
CHECK_INTERVAL = timedelta(hours=24)
USER_AGENT = "AutomationStudio-Updater"


class UpdateError(Exception):
    pass


def parse_version(text: str) -> tuple[int, ...]:
    nums = re.findall(r"\d+", text)
    if not nums:
        raise UpdateError(f"not a version: {text!r}")
    return tuple(int(n) for n in nums[:4])


@dataclass
class Release:
    version: str
    download_url: str | None
    sha256: str | None
    notes: str
    page_url: str | None


def authenticode(path: Path) -> tuple[str, str | None]:
    """(status, signer thumbprint) via PowerShell's Get-AuthenticodeSignature."""
    if sys.platform != "win32":
        return "Unsupported", None
    script = (
        "$s = Get-AuthenticodeSignature -LiteralPath $args[0]; "
        "@{status = [string]$s.Status; thumbprint = $s.SignerCertificate.Thumbprint} | ConvertTo-Json -Compress"
    )
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script, str(path)],
            capture_output=True, text=True, timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        data = json.loads(out.stdout or "{}")
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        return f"Error: {exc}", None
    return data.get("status") or "Unknown", data.get("thumbprint")


class UpdateManager:
    def __init__(self, current_version: str, *, download_dir: Path = paths.DATA_DIR / "updates",
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.current_version = current_version
        self.download_dir = download_dir
        self._transport = transport
        self.source: str | None = None
        self.latest: Release | None = None
        self.checked_at: datetime | None = None
        self.error: str | None = None
        self.state = "idle"  # idle | checking | downloading | verifying | installing
        self._lock = asyncio.Lock()

    # ---- status

    @property
    def available(self) -> bool:
        if self.latest is None:
            return False
        try:
            return parse_version(self.latest.version) > parse_version(self.current_version)
        except UpdateError:
            return False

    def status(self) -> dict[str, Any]:
        can_install, reason = self.install_preconditions()
        return {
            "current_version": self.current_version,
            "source": self.source,
            "state": self.state,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "error": self.error,
            "available": self.available,
            "latest": asdict(self.latest) if self.latest else None,
            "can_auto_install": can_install,
            "auto_install_blocked_reason": reason,
        }

    def install_preconditions(self) -> tuple[bool, str | None]:
        if not self.available or self.latest is None:
            return False, "no update available"
        if not paths.FROZEN:
            return False, "running from source: update with git and rebuild"
        if not paths.installed_copy():
            return False, "portable copy: download the new zip from the release page"
        if not self.latest.download_url:
            return False, "the release has no installer download"
        return True, None

    def due(self) -> bool:
        return bool(self.source) and (self.checked_at is None or datetime.now(timezone.utc) - self.checked_at > CHECK_INTERVAL)

    # ---- checking

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=self._transport, follow_redirects=True, timeout=60,
                                 headers={"User-Agent": USER_AGENT})

    async def check(self) -> dict[str, Any]:
        async with self._lock:
            if not self.source:
                self.error = "no update source configured"
                return self.status()
            self.state, self.error = "checking", None
            try:
                async with self._client() as client:
                    self.latest = await self._fetch(client, self.source)
                self.checked_at = datetime.now(timezone.utc)
                if self.available:
                    logger.info("update available: %s -> %s", self.current_version, self.latest.version)
            except (UpdateError, httpx.HTTPError, ValueError, KeyError) as exc:
                self.error = f"update check failed: {exc}"
                logger.warning(self.error)
            finally:
                self.state = "idle"
            return self.status()

    async def _fetch(self, client: httpx.AsyncClient, source: str) -> Release:
        if source.startswith("github:"):
            repo = source.removeprefix("github:").strip("/")
            if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
                raise UpdateError("github source must look like github:owner/repo")
            resp = await client.get(f"https://api.github.com/repos/{repo}/releases/latest",
                                    headers={"Accept": "application/vnd.github+json"})
            if resp.status_code == 404:
                raise UpdateError(f"no published release found for {repo}")
            resp.raise_for_status()
            rel = resp.json()
            asset = next((a for a in rel.get("assets", []) if re.search(r"setup.*\.exe$", a["name"], re.I)), None)
            digest = (asset or {}).get("digest") or ""
            return Release(
                version=rel["tag_name"].lstrip("vV"),
                download_url=asset["browser_download_url"] if asset else None,
                sha256=digest.removeprefix("sha256:") if digest.startswith("sha256:") else None,
                notes=rel.get("body") or "",
                page_url=rel.get("html_url"),
            )
        if not source.startswith("https://"):
            raise UpdateError("update source must be github:owner/repo or an https:// manifest URL")
        resp = await client.get(source)
        resp.raise_for_status()
        m = resp.json()
        url = m.get("url")
        if url and not str(url).startswith("https://"):
            raise UpdateError("installer URL must be https")
        return Release(version=str(m["version"]), download_url=url, sha256=(m.get("sha256") or None),
                       notes=m.get("notes", ""), page_url=m.get("page") or url)

    # ---- installing

    async def download_and_verify(self) -> Path:
        ok, reason = self.install_preconditions()
        if not ok:
            raise UpdateError(reason or "cannot install")
        assert self.latest is not None and self.latest.download_url
        release = self.latest
        self.download_dir.mkdir(parents=True, exist_ok=True)
        target = self.download_dir / f"AutomationStudio-Setup-{release.version}.exe"
        part = target.with_suffix(".part")
        self.state = "downloading"
        try:
            digest = hashlib.sha256()
            async with self._client() as client, client.stream("GET", release.download_url) as resp:
                resp.raise_for_status()
                with open(part, "wb") as f:
                    async for chunk in resp.aiter_bytes(1 << 16):
                        f.write(chunk)
                        digest.update(chunk)
            self.state = "verifying"
            await asyncio.to_thread(self._verify, part, digest.hexdigest(), release)
            part.replace(target)
            return target
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        finally:
            self.state = "idle"

    def _verify(self, file: Path, sha256: str, release: Release) -> None:
        own_status, own_thumb = authenticode(Path(sys.executable)) if paths.FROZEN else ("NotSigned", None)
        if own_status == "Valid" and own_thumb:
            status, thumb = authenticode(file)
            if status != "Valid" or (thumb or "").upper() != own_thumb.upper():
                raise UpdateError(f"installer signature check failed ({status}, signer {thumb}); not installing")
            logger.info("update verified: signed by %s", thumb)
            return
        if not release.sha256:
            raise UpdateError("this build is unsigned and the release publishes no SHA-256; "
                              "download it manually from the release page")
        if sha256.lower() != release.sha256.lower():
            raise UpdateError("installer SHA-256 does not match the published digest; not installing")
        logger.info("update verified: sha256 %s", sha256)

    def launch_installer(self, installer: Path) -> None:
        """Run the installer detached. It stops this service itself and relaunches the app."""
        self.state = "installing"
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        subprocess.Popen([str(installer), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/relaunch=1"],
                         creationflags=flags, close_fds=True)
