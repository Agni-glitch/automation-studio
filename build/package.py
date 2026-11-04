"""Build AutomationStudio.exe and its installer.

    python build/package.py                 # everything
    python build/package.py --skip-frontend # reuse frontend/dist
    python build/package.py --no-installer  # only the program folder

Steps
  1. frontend: npm ci (first time) + npm run build -> frontend/dist
  2. icon + Windows version resource
  3. official embeddable CPython from python.org (runs Python Script nodes), cached in build/cache
  4. PyInstaller -> build/output/dist/AutomationStudio/{AutomationStudio.exe, studio.exe, _internal/}
  5. copy the embeddable Python into _internal/python and smoke-test the result
  6. Inno Setup -> build/output/AutomationStudio-Setup-<version>.exe
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

BUILD = Path(__file__).resolve().parent
ROOT = BUILD.parent
OUTPUT = BUILD / "output"
CACHE = BUILD / "cache"
DIST = OUTPUT / "dist" / "AutomationStudio"
sys.path.insert(0, str(ROOT))

from backend import APP_NAME, __version__  # noqa: E402


def step(title: str) -> None:
    print(f"\n=== {title}", flush=True)


def run(cmd: list[str], cwd: Path = ROOT, **kw) -> subprocess.CompletedProcess:
    print("  $", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run([str(c) for c in cmd], cwd=cwd, check=True, **kw)


def build_frontend(clean: bool) -> None:
    step("frontend")
    frontend = ROOT / "frontend"
    npm = shutil.which("npm.cmd") or shutil.which("npm")
    if not npm:
        sys.exit("npm not found: install Node.js 20+ (https://nodejs.org)")
    if clean or not (frontend / "node_modules").exists():
        run([npm, "ci"], cwd=frontend)
    run([npm, "run", "build"], cwd=frontend)


def write_version_file() -> Path:
    parts = [int(p) for p in __version__.split(".")] + [0] * 4
    tup = tuple(parts[:4])
    path = OUTPUT / "version_info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', '{APP_NAME}'),
      StringStruct('FileDescription', '{APP_NAME}'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('ProductName', '{APP_NAME}'),
      StringStruct('ProductVersion', '{__version__}'),
      StringStruct('LegalCopyright', ''),
    ])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
""", encoding="utf-8")
    return path


def embedded_python() -> Path:
    """Official embeddable CPython, same version as the build interpreter."""
    step("embeddable Python")
    version = platform.python_version()
    target = CACHE / f"python-{version}-embed-amd64"
    if (target / "python.exe").exists():
        print(f"  cached: {target}")
        return target
    url = f"https://www.python.org/ftp/python/{version}/python-{version}-embed-amd64.zip"
    archive = CACHE / f"python-{version}-embed-amd64.zip"
    CACHE.mkdir(parents=True, exist_ok=True)
    print(f"  downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as resp, open(archive, "wb") as f:
        shutil.copyfileobj(resp, f)
    tmp = target.with_suffix(".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    with zipfile.ZipFile(archive) as zf:
        if zf.testzip() is not None:
            sys.exit("downloaded Python archive is corrupt")
        zf.extractall(tmp)
    out = subprocess.run([str(tmp / "python.exe"), "-c", "import sys, json, sqlite3, ssl; print(sys.version)"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0 or not out.stdout.startswith(version):
        sys.exit(f"embedded Python self-test failed: {out.stdout}{out.stderr}")
    tmp.rename(target)
    print(f"  ok: Python {out.stdout.strip().split()[0]}")
    return target


def pyinstaller() -> None:
    step("PyInstaller")
    shutil.rmtree(DIST, ignore_errors=True)
    run([sys.executable, "-m", "PyInstaller", BUILD / "AutomationStudio.spec", "--noconfirm", "--log-level", "WARN",
         "--distpath", OUTPUT / "dist", "--workpath", OUTPUT / "work"])


def finish_bundle(python_dir: Path) -> None:
    step("bundle python + smoke test")
    internal = DIST / "_internal"
    shutil.copytree(python_dir, internal / "python", dirs_exist_ok=True)
    cli = DIST / "studio.exe"
    for exe in ("AutomationStudio.exe", "studio.exe"):
        if not (DIST / exe).exists():
            sys.exit(f"missing {exe}")
    # CLI parses and imports everything (exit 1 = service not running, which is fine here)
    res = subprocess.run([str(cli), "status"], capture_output=True, text=True, timeout=120)
    if "service:" not in res.stdout:
        sys.exit(f"studio.exe smoke test failed:\n{res.stdout}\n{res.stderr}")
    print("  studio.exe status ->", res.stdout.strip().splitlines()[0])
    size = sum(f.stat().st_size for f in DIST.rglob("*") if f.is_file())
    print(f"  bundle: {DIST} ({size / 1e6:.0f} MB)")


SIGN_VARS = ("STUDIO_SIGN_THUMBPRINT", "STUDIO_SIGN_PFX", "STUDIO_SIGN_COMMAND")
SIGN_SCRIPT = BUILD / "sign.ps1"


def signing_configured() -> bool:
    return any(os.environ.get(v) for v in SIGN_VARS)


def sign_command(file: str) -> list[str]:
    return ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(SIGN_SCRIPT), file]


def sign_bundle() -> None:
    step("code signing (exes)")
    for exe in ("AutomationStudio.exe", "studio.exe"):
        run(sign_command(str(DIST / exe)))


def write_build_info(update_source: str | None) -> None:
    info = {"version": __version__, "update_source": update_source,
            "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    (DIST / "_internal" / "build_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(f"  build_info: update source = {update_source or '(none)'}")


def write_manifest(setup: Path, update_source: str | None, download_base: str | None = None) -> None:
    """latest.json for manifest-based updates: host it (and the installer) and point the app's
    update source at its https URL. ``download_base`` is where the installer will live."""
    digest = hashlib.sha256(setup.read_bytes()).hexdigest()
    base = (download_base or "https://REPLACE-ME").rstrip("/")
    manifest = {"version": __version__, "url": f"{base}/{setup.name}", "sha256": digest,
                "notes": "", "page": None}
    (OUTPUT / "latest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"  sha256 {digest}")
    print(f"  manifest: {OUTPUT / 'latest.json'}" + ("" if update_source else "  (no update source baked in)"))


def find_iscc() -> Path | None:
    for candidate in (
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Inno Setup 6" / "ISCC.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Inno Setup 6" / "ISCC.exe",
    ):
        if candidate.exists():
            return candidate
    found = shutil.which("iscc")
    return Path(found) if found else None


def installer(sign: bool) -> Path:
    step("installer (Inno Setup)" + (" + signing" if sign else ""))
    iscc = find_iscc()
    if iscc is None:
        sys.exit("Inno Setup 6 not found: winget install JRSoftware.InnoSetup --scope user")
    cmd: list = [iscc, "/Q", f"/DAppVersion={__version__}", f"/DSourceDir={DIST}", f"/DOutputDir={OUTPUT}"]
    if sign:
        # Inno replaces $f with the quoted file to sign (setup and uninstaller)
        cmd += ["/DSign", "/Sstudio=" + subprocess.list2cmdline(sign_command("FILE")).replace("FILE", "$f")]
    run([*cmd, BUILD / "installer.iss"], cwd=BUILD)
    setup = OUTPUT / f"AutomationStudio-Setup-{__version__}.exe"
    print(f"  {setup} ({setup.stat().st_size / 1e6:.0f} MB)")
    return setup


def main() -> None:
    if sys.platform != "win32":
        sys.exit("the Windows build must run on Windows")
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--skip-frontend", action="store_true")
    p.add_argument("--no-installer", action="store_true")
    p.add_argument("--clean", action="store_true", help="fresh npm ci and PyInstaller work dir")
    p.add_argument("--update-source", default=os.environ.get("STUDIO_UPDATE_SOURCE"),
                   help="default update source baked into the app: github:owner/repo or https://.../latest.json")
    p.add_argument("--download-base", help="URL prefix where the installer will be hosted (for latest.json)")
    sign_group = p.add_mutually_exclusive_group()
    sign_group.add_argument("--sign", action="store_true", help="require code signing (fails if not configured)")
    sign_group.add_argument("--no-sign", action="store_true", help="skip code signing even if configured")
    args = p.parse_args()
    if args.sign and not signing_configured():
        sys.exit(f"--sign: set one of {', '.join(SIGN_VARS)} (see build/sign.ps1)")
    sign = signing_configured() and not args.no_sign

    started = time.time()
    if args.clean:
        shutil.rmtree(OUTPUT, ignore_errors=True)
    if not args.skip_frontend:
        build_frontend(args.clean)
    elif not (ROOT / "frontend" / "dist" / "index.html").exists():
        sys.exit("frontend/dist is missing; run without --skip-frontend")
    step("icon + version resource")
    if not (BUILD / "assets" / "app.ico").exists():
        run([sys.executable, BUILD / "make_icon.py"])
    write_version_file()
    python_dir = embedded_python()
    pyinstaller()
    write_build_info(args.update_source)
    finish_bundle(python_dir)
    if sign:
        sign_bundle()
    else:
        print("\n  (unsigned: SmartScreen will warn on other PCs; see build/sign.ps1)")
    if not args.no_installer:
        setup = installer(sign)
        write_manifest(setup, args.update_source, args.download_base)
    print(f"\nDone in {time.time() - started:.0f}s. Program folder: {DIST}")


if __name__ == "__main__":
    main()
