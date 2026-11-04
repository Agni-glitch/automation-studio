"""Build and publish a release.

    python build/release.py --notes-file notes.md      # bump backend/__init__.py __version__ first
    python build/release.py --notes "What changed"
    python build/release.py --dry-run                   # build + checks, publish nothing

1. checks: clean git tree, version not released yet, gh logged in, commit pushed
2. builds with the update source baked in (github:<releases_repo>): installer, portable zip,
   SHA256SUMS.txt, latest.json
3. tags the source commit v<version> and pushes the tag
4. creates release v<version> in <releases_repo> from that tag with all four files, then the
   same release in each of <mirror_repos> (older installs check those for updates)
5. verifies GitHub's published SHA-256 digest of the installer equals the local file in every
   repo (the updater relies on it)

Config: build/release.json. Signing: same env vars as package.py; pass --sign to require it.
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
OUTPUT = BUILD / "output"
sys.path.insert(0, str(ROOT))

from backend import __version__  # noqa: E402

CONFIG = json.loads((BUILD / "release.json").read_text(encoding="utf-8"))
REPO = CONFIG["releases_repo"]
MIRRORS: list[str] = CONFIG.get("mirror_repos", [])
REMOTE = CONFIG.get("source_remote", "origin")
TAG = f"v{__version__}"
SETUP = OUTPUT / f"AutomationStudio-Setup-{__version__}.exe"
PORTABLE = OUTPUT / f"AutomationStudio-{__version__}-portable.zip"
SUMS = OUTPUT / "SHA256SUMS.txt"
MANIFEST = OUTPUT / "latest.json"


def sh(*cmd: str, check: bool = True) -> str:
    res = subprocess.run(list(cmd), cwd=ROOT, capture_output=True, text=True)
    if check and res.returncode != 0:
        sys.exit(f"failed: {' '.join(cmd)}\n{(res.stderr or res.stdout or '').strip()}")
    return (res.stdout or "").strip()


def released(repo: str) -> bool:
    return subprocess.run(["gh", "release", "view", TAG, "--repo", repo], cwd=ROOT,
                          capture_output=True).returncode == 0


def preflight() -> None:
    if sh("git", "status", "--porcelain"):
        sys.exit("working tree has uncommitted changes; commit them first")
    if released(REPO):
        sys.exit(f"{TAG} is already published in {REPO}; bump __version__ in backend/__init__.py")
    sh("gh", "auth", "status")
    head = sh("git", "rev-parse", "HEAD")
    if head not in sh("git", "ls-remote", REMOTE) and REMOTE + "/" not in sh("git", "branch", "-r", "--contains", head, check=False):
        sys.exit(f"HEAD {head[:8]} is not pushed to '{REMOTE}'; push it first")


def build(extra: list[str]) -> None:
    download_base = f"https://github.com/{REPO}/releases/download/{TAG}"
    subprocess.run([sys.executable, str(BUILD / "package.py"), "--update-source", f"github:{REPO}",
                    "--download-base", download_base, *extra], cwd=ROOT, check=True)
    for f in (SETUP, PORTABLE, SUMS, MANIFEST):
        if not f.exists():
            sys.exit(f"build did not produce {f}")


def tag_source() -> None:
    head = sh("git", "rev-parse", "HEAD")
    existing = sh("git", "rev-parse", "-q", "--verify", f"refs/tags/{TAG}^{{commit}}", check=False)
    if existing and existing != head:
        sys.exit(f"tag {TAG} already exists on another commit")
    if not existing:
        sh("git", "tag", "-a", TAG, "-m", f"Release {__version__}")
    sh("git", "push", REMOTE, TAG)
    print(f"tagged source {TAG}")


def release_body(notes: str, repo: str) -> str:
    size = lambda f: f"{f.stat().st_size / 1e6:.0f} MB"  # noqa: E731
    body = f"{notes.strip()}\n\n" if notes.strip() else ""
    if repo != REPO:
        body = (f"Mirror of [{TAG}](https://github.com/{REPO}/releases/tag/{TAG}). New releases are "
                f"published in [{REPO}](https://github.com/{REPO}/releases); installing this one "
                f"switches the app's update checks there.\n\n") + body
    sums = SUMS.read_text(encoding="utf-8").strip()
    return body + (
        "## Downloads\n\n"
        "| File | What it is |\n|---|---|\n"
        f"| **`{SETUP.name}`** ({size(SETUP)}) | **Recommended.** Installer for your user account, no "
        "admin rights needed. Adds Start menu and desktop shortcuts and keeps itself up to date. |\n"
        f"| `{PORTABLE.name}` ({size(PORTABLE)}) | Portable copy: unzip anywhere and run "
        "`AutomationStudio.exe`. Nothing is installed; it doesn't update itself. |\n"
        "| `SHA256SUMS.txt` | Checksums of both files. |\n"
        "| `latest.json` | Update manifest read by the app. |\n\n"
        "Requires Windows 10 (1809+) or 11, 64-bit. The app isn't code-signed yet, so Windows may show "
        "\"Windows protected your PC\": choose **More info → Run anyway**.\n\n"
        f"### SHA-256\n```\n{sums}\n```\n"
        "Check a download with `Get-FileHash .\\<file>` in PowerShell.\n")


def publish(repo: str, notes: str, source_tag: bool) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
        f.write(release_body(notes, repo))
    cmd = ["gh", "release", "create", TAG, str(SETUP), str(PORTABLE), str(SUMS), str(MANIFEST),
           "--repo", repo, "--title", f"Automation Studio {__version__}", "--notes-file", f.name, "--latest"]
    if source_tag:
        cmd.append("--verify-tag")
    sh(*cmd)
    Path(f.name).unlink(missing_ok=True)

    sha = hashlib.sha256(SETUP.read_bytes()).hexdigest()
    assets = json.loads(sh("gh", "api", f"repos/{repo}/releases/tags/{TAG}"))["assets"]
    published = next(a for a in assets if a["name"] == SETUP.name)
    digest = (published.get("digest") or "").removeprefix("sha256:")
    if digest != sha:
        sys.exit(f"{repo}: GitHub digest {digest or '(missing)'} != local {sha}: updates would be refused")
    print(f"published https://github.com/{repo}/releases/tag/{TAG} (sha256 verified)")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--notes", default="", help="release notes (markdown)")
    p.add_argument("--notes-file", type=Path, help="release notes from a markdown file")
    p.add_argument("--dry-run", action="store_true", help="build and check, but publish nothing")
    p.add_argument("--sign", action="store_true", help="require code signing")
    p.add_argument("--skip-frontend", action="store_true")
    args = p.parse_args()
    notes = args.notes_file.read_text(encoding="utf-8") if args.notes_file else args.notes

    if not args.dry_run:
        preflight()
    build((["--sign"] if args.sign else []) + (["--skip-frontend"] if args.skip_frontend else []))
    if args.dry_run:
        print(release_body(notes, REPO))
        print(f"dry run: would publish {TAG} to {REPO}" + (f" and {', '.join(MIRRORS)}" if MIRRORS else ""))
        return
    tag_source()
    publish(REPO, notes, source_tag=True)
    for mirror in MIRRORS:
        if not released(mirror):
            publish(mirror, notes, source_tag=False)


if __name__ == "__main__":
    main()
