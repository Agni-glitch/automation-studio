# Building and releasing

## Build the Windows app

You need Python 3.11+, Node.js 20+ and Inno Setup 6
(`winget install JRSoftware.InnoSetup --scope user`). Then, from the repository root:

```powershell
build_windows.bat
```

or, with your own virtual environment active:

```powershell
pip install -e ".[browser,desktop,build]"
python build/package.py
```

| Option | Effect |
|---|---|
| `--skip-frontend` | reuse `frontend/dist` instead of rebuilding the editor |
| `--no-installer` | build only the program folder |
| `--no-portable` | skip the portable zip |
| `--clean` | fresh `npm ci` and PyInstaller work folder |
| `--update-source github:owner/repo` | the update source baked into the app |
| `--sign` / `--no-sign` | require code signing, or skip it even if configured |

The build takes about two minutes and writes to `build/output/`:

| Output | What it is |
|---|---|
| `dist/AutomationStudio/` | the program folder (about 210 MB): `AutomationStudio.exe`, `studio.exe` and `_internal/`, which includes an embeddable CPython for Python Script nodes |
| `AutomationStudio-Setup-<version>.exe` | the installer (about 76 MB) |
| `AutomationStudio-<version>-portable.zip` | the program folder as a zip |
| `SHA256SUMS.txt` | checksums of the installer and the zip |
| `latest.json` | update manifest, for hosting updates somewhere other than GitHub |

The installer installs per-user into `%LOCALAPPDATA%\Programs\AutomationStudio` without an
admin prompt, creates Start menu and desktop shortcuts, and can enable start-at-sign-in. It
stops a running service before upgrading or uninstalling. Uninstalling keeps user data in
`%LOCALAPPDATA%\AutomationEngine`.

The packaged app's browser automation uses the installed Edge or Chrome; Playwright's own
`chromium`, `firefox` and `webkit` browsers aren't bundled.

## Publish a release

Releases are published to this repository's
[Releases](https://github.com/Agni-glitch/automation-studio/releases) page, which installed
copies check for updates.

1. Bump `__version__` in `backend/__init__.py` (and `version` in `pyproject.toml` and
   `frontend/package.json`), add the changes to `CHANGELOG.md`, and get it merged into `main`.
2. Write the release notes in a Markdown file and run:

   ```powershell
   python build/release.py --notes-file notes.md
   ```

The script:

1. refuses to run with uncommitted or unpushed changes, or for a version that's already
   released;
2. builds with the update source baked in;
3. tags the commit `v<version>` and pushes the tag;
4. creates the GitHub release from that tag with the installer, the portable zip,
   `SHA256SUMS.txt` and `latest.json`, and adds a downloads table and checksums to the notes;
5. checks that GitHub's published SHA-256 of the installer matches the local file, because
   unsigned builds only install updates whose digest matches;
6. publishes the same release to each repository in `mirror_repos` (in `build/release.json`).
   The old `automation-studio-releases` repository is a mirror, so copies of 0.2.0, which check
   there, still get updates.

`--dry-run` builds and prints the release notes without publishing anything; `--sign` requires
code signing.

## Code signing

Unsigned builds trigger SmartScreen's *"Windows protected your PC"* on other machines. With a
certificate, set one environment variable and build. Both executables, the installer and the
uninstaller are then signed and timestamped:

```bat
set STUDIO_SIGN_THUMBPRINT=<thumbprint>        & rem a certificate in your Windows store (including USB-token/EV)
rem   or STUDIO_SIGN_PFX=<file.pfx> and STUDIO_SIGN_PFX_PASSWORD=<password>
rem   or STUDIO_SIGN_COMMAND=<any signing command, {file} = path>   (Azure Trusted Signing, SignPath, ...)
build_windows.bat --sign
```

Certificates come from a public CA (OV or EV code-signing, usually on a hardware token or cloud
HSM), Microsoft's Azure Trusted Signing, or SignPath, which is free for open-source projects.
SmartScreen reputation builds up per certificate over downloads.

Once releases are signed, the updater switches from checksum verification to requiring a
valid signature from the same certificate as the running app.

## How updates work

The app checks its update source once a day. The source is `github:owner/repo` (the latest
release's `*Setup*.exe` asset) or an `https://` URL to a `latest.json` manifest. When you choose
**Install update**, it downloads the installer and verifies it before running it:

- **Signed app:** the download must have a valid signature from the same certificate.
- **Unsigned app:** the download's SHA-256 must match the digest GitHub publishes (or the
  manifest's `sha256`).

If neither check is possible, it refuses and points to the release page. The installer then runs
silently, stops the service, upgrades and reopens the app. The portable zip and source checkouts
show available updates but never install over themselves.
