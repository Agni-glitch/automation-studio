"""Build and publish a release.

    python build/release.py --notes "What changed"      # bump backend/__init__.py __version__ first
    python build/release.py --dry-run                   # build + checks, publish nothing

1. checks: clean git tree, version not released yet, gh logged in, commit pushed
2. builds with the update source baked in (github:<releases_repo>)
3. creates release v<version> in the public releases repo with the installer + latest.json
4. verifies GitHub's published SHA-256 digest equals the local installer's (the updater relies on it)
5. tags the source commit v<version> and pushes the tag

Config: build/release.json ("releases_repo"). Signing: same env vars as package.py; pass
--sign to require it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

BUILD = Path(__file__).resolve().parent
ROOT = BUILD.parent
sys.path.insert(0, str(ROOT))

from backend import __version__  # noqa: E402

CONFIG = json.loads((BUILD / "release.json").read_text(encoding="utf-8"))
REPO = CONFIG["releases_repo"]
REMOTE = CONFIG.get("source_remote", "origin")
TAG = f"v{__version__}"


def sh(*cmd: str, capture: bool = True, check: bool = True) -> str:
    res = subprocess.run(list(cmd), cwd=ROOT, capture_output=capture, text=True)
    if check and res.returncode != 0:
        sys.exit(f"failed: {' '.join(cmd)}\n{(res.stderr or res.stdout or '').strip()}")
    return (res.stdout or "").strip()


def preflight() -> None:
    if sh("git", "status", "--porcelain"):
        sys.exit("working tree has uncommitted changes; commit them first")
    if subprocess.run(["gh", "release", "view", TAG, "--repo", REPO], cwd=ROOT,
                      capture_output=True).returncode == 0:
        sys.exit(f"{TAG} is already published in {REPO}; bump __version__ in backend/__init__.py")
    sh("gh", "auth", "status")
    head = sh("git", "rev-parse", "HEAD")
    remote_heads = sh("git", "ls-remote", REMOTE, "HEAD")
    if head not in remote_heads and head not in sh("git", "branch", "-r", "--contains", head, check=False):
        sys.exit(f"HEAD {head[:8]} is not pushed to '{REMOTE}'; push it first")


def build(extra: list[str]) -> Path:
    download_base = f"https://github.com/{REPO}/releases/download/{TAG}"
    subprocess.run([sys.executable, str(BUILD / "package.py"), "--update-source", f"github:{REPO}",
                    "--download-base", download_base, *extra], cwd=ROOT, check=True)
    setup = BUILD / "output" / f"AutomationStudio-Setup-{__version__}.exe"
    if not setup.exists():
        sys.exit(f"build did not produce {setup}")
    return setup


def publish(setup: Path, notes: str) -> None:
    sha = hashlib.sha256(setup.read_bytes()).hexdigest()
    body = (f"{notes.strip()}\n\n" if notes.strip() else "") + (
        f"**Install:** download `{setup.name}` and run it (per-user, no admin needed).\n\n"
        f"SHA-256 of `{setup.name}`:\n```\n{sha}\n```\n")
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(body)
    sh("gh", "release", "create", TAG, str(setup), str(BUILD / "output" / "latest.json"),
       "--repo", REPO, "--title", f"Automation Studio {__version__}", "--notes-file", f.name, "--latest")
    Path(f.name).unlink(missing_ok=True)

    assets = json.loads(sh("gh", "api", f"repos/{REPO}/releases/tags/{TAG}"))["assets"]
    published = next(a for a in assets if a["name"] == setup.name)
    digest = (published.get("digest") or "").removeprefix("sha256:")
    if digest != sha:
        sys.exit(f"GitHub digest {digest or '(missing)'} != local {sha}: updates would be refused; check the release")
    print(f"published {TAG} to https://github.com/{REPO}/releases/tag/{TAG} (sha256 verified)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--notes", default="", help="release notes (markdown)")
    p.add_argument("--dry-run", action="store_true", help="build and check, but publish nothing")
    p.add_argument("--sign", action="store_true", help="require code signing")
    p.add_argument("--skip-frontend", action="store_true")
    args = p.parse_args()

    if not args.dry_run:
        preflight()
    setup = build((["--sign"] if args.sign else []) + (["--skip-frontend"] if args.skip_frontend else []))
    if args.dry_run:
        print(f"dry run: would publish {setup.name} as {TAG} to {REPO}")
        return
    publish(setup, args.notes)
    sh("git", "tag", "-a", TAG, "-m", f"Release {__version__}")
    sh("git", "push", REMOTE, TAG)
    print(f"tagged source {TAG}")


if __name__ == "__main__":
    main()
