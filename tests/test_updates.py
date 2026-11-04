import asyncio
import hashlib

import httpx
import pytest

from backend import paths, updates
from backend.service import StudioService
from backend.updates import UpdateError, UpdateManager, parse_version
from database import Database, StaticKeyStore

INSTALLER = b"MZ fake installer bytes"
SHA = hashlib.sha256(INSTALLER).hexdigest()


def github_handler(tag="v0.3.0", digest=f"sha256:{SHA}", assets=True):
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "api.github.com":
            assert req.url.path == "/repos/acme/studio/releases/latest"
            assert req.headers["user-agent"].startswith("AutomationStudio")
            return httpx.Response(200, json={
                "tag_name": tag, "body": "Faster runs", "html_url": "https://github.com/acme/studio/releases/v0.3.0",
                "assets": [{"name": "AutomationStudio-Setup-0.3.0.exe", "digest": digest,
                            "browser_download_url": "https://github.com/acme/studio/releases/download/v0.3.0/Setup.exe"},
                           {"name": "latest.json", "browser_download_url": "https://x/latest.json"}] if assets else [],
            })
        if req.url.path.endswith("Setup.exe"):
            return httpx.Response(200, content=INSTALLER)
        return httpx.Response(404)
    return handler


def manager(handler, current="0.2.0") -> UpdateManager:
    m = UpdateManager(current, transport=httpx.MockTransport(handler))
    m.source = "github:acme/studio"
    return m


def test_parse_version():
    assert parse_version("v1.10.0") > parse_version("1.9.9")
    with pytest.raises(UpdateError):
        parse_version("latest")


def test_github_release_check():
    m = manager(github_handler())
    status = asyncio.run(m.check())
    assert status["available"] and status["latest"]["version"] == "0.3.0"
    assert status["latest"]["sha256"] == SHA and status["error"] is None
    assert status["auto_install_blocked_reason"] == "running from source: update with git and rebuild"

    same = asyncio.run(manager(github_handler(tag="v0.2.0")).check())
    assert same["available"] is False


def test_manifest_source_and_validation():
    def handler(req):
        return httpx.Response(200, json={"version": "0.4.0", "url": "https://example.com/Setup.exe", "sha256": SHA})

    m = manager(handler)
    m.source = "https://example.com/latest.json"
    assert asyncio.run(m.check())["latest"]["version"] == "0.4.0"

    m.source = "http://insecure.example/latest.json"
    assert "https://" in asyncio.run(m.check())["error"]

    def plain_http_installer(req):
        return httpx.Response(200, json={"version": "0.4.0", "url": "http://example.com/Setup.exe"})

    m2 = manager(plain_http_installer)
    m2.source = "https://example.com/latest.json"
    assert "must be https" in asyncio.run(m2.check())["error"]


def test_download_verifies_sha256(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "FROZEN", True)
    monkeypatch.setattr(updates, "authenticode", lambda p: ("NotSigned", None))  # unsigned build

    m = manager(github_handler())
    m.download_dir = tmp_path
    asyncio.run(m.check())
    path = asyncio.run(m.download_and_verify())
    assert path.read_bytes() == INSTALLER

    bad = manager(github_handler(digest="sha256:" + "0" * 64))
    bad.download_dir = tmp_path / "bad"
    asyncio.run(bad.check())
    with pytest.raises(UpdateError, match="does not match"):
        asyncio.run(bad.download_and_verify())
    assert not list((tmp_path / "bad").glob("*"))  # partial download removed

    none = manager(github_handler(digest=None))
    none.download_dir = tmp_path / "none"
    asyncio.run(none.check())
    with pytest.raises(UpdateError, match="no SHA-256"):
        asyncio.run(none.download_and_verify())


def test_signed_build_requires_same_signer(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "FROZEN", True)
    signer = {"current": ("Valid", "ABC123"), "download": ("Valid", "ABC123")}
    monkeypatch.setattr(updates, "authenticode",
                        lambda p: signer["download"] if p.suffix == ".part" else signer["current"])
    m = manager(github_handler(digest=None))  # signature replaces the need for a digest
    m.download_dir = tmp_path
    asyncio.run(m.check())
    assert asyncio.run(m.download_and_verify()).exists()

    signer["download"] = ("Valid", "EVIL999")
    with pytest.raises(UpdateError, match="signature check failed"):
        asyncio.run(m.download_and_verify())


def test_update_api_and_settings(tmp_path):
    async def go():
        db = Database(tmp_path / "u.db", key_store=StaticKeyStore())
        svc = StudioService(db, api_port=0, webhook_port=0, token="t" * 40, bin_dir=tmp_path / "bin",
                            service_file=None, updates=UpdateManager("0.2.0", transport=httpx.MockTransport(github_handler())))
        await svc.start()
        try:
            async with httpx.AsyncClient(base_url=svc.api_url, headers={"X-Studio-Token": "t" * 40}) as c:
                bad = await c.put("/api/updates/settings", json={"source": "ftp://nope"})
                await c.put("/api/updates/settings", json={"source": "github:acme/studio", "auto_check": False})
                checked = (await c.post("/api/updates/check")).json()
                status = (await c.get("/api/status")).json()["updates"]
                install = await c.post("/api/updates/install")
        finally:
            await svc.stop()
            db.close()
        return bad, checked, status, install

    bad, checked, status, install = asyncio.run(go())
    assert bad.status_code == 400
    assert checked["available"] and status["source"] == "github:acme/studio" and status["auto_check"] is False
    assert install.status_code == 400 and "source" in install.json()["detail"]  # not frozen -> refused
