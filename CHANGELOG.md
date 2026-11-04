# Changelog

All notable changes to Automation Studio. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Hands-on labs in `docs/labs`: twelve step-by-step exercises, from a first run to an
  unattended AI digest, covering every trigger and node.
- Seven example workflows: `weather_alert`, `folder_sorter`, `retry_and_errors`,
  `secure_webhook`, `hn_headlines`, `notepad_desktop` and `daily_digest`.

## [0.2.2] - 2026-11-04

### Fixed
- The app no longer quits silently at launch when another window shares its title, such as a
  File Explorer tab on a folder named "Automation Studio". Only the app's own window counts as
  already open.

### Changed
- Editor updated to React 19, TypeScript 7 and Vite 8, with newer React Flow and CodeMirror.
- Minimum versions raised for FastAPI, uvicorn, websockets, httpx, Playwright and PyInstaller.
- CI uses `actions/checkout`, `actions/setup-python` and `actions/setup-node` v7.

## [0.2.1] - 2026-11-04

### Added
- Portable zip and `SHA256SUMS.txt` in every release, alongside the installer.
- MIT license, contributing guide, code of conduct, security policy, and issue and pull
  request templates.
- CI on Windows for the test suite and the editor build.

### Changed
- Releases are published from the main repository, and the app checks it for updates. The
  old downloads repository mirrors each release, so 0.2.0 installs keep updating.
- The installer creates a desktop shortcut by default and installs the license.
- Documentation moved into `docs/`, with new getting-started, node reference and CLI guides.

### Fixed
- Portable copies no longer try to install updates over themselves.

## [0.2.0] - 2026-11-04

First release.

- Visual workflow editor (React Flow) in a desktop window, with live run status and logs.
- Workflow engine with parallel branches, If routing, retries, timeouts and error outputs.
- Triggers: manual, webhook, folder watcher, schedule.
- Nodes: AI Agent (Anthropic, OpenAI, Ollama), Python Script (sandboxed), HTTP Request,
  Send Email, Social Post (LinkedIn), Browser Automation, Desktop Automation, Set, If, Wait.
- Encrypted credential vault (Fernet + Windows DPAPI) and run history in SQLite.
- Background service with tray icon, start at sign-in, Cloudflare Tunnel for public webhooks,
  and verified in-app updates.
- `studio` command line.
- Per-user installer.

[Unreleased]: https://github.com/Agni-glitch/automation-studio/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/Agni-glitch/automation-studio/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/Agni-glitch/automation-studio/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/Agni-glitch/automation-studio/releases/tag/v0.2.0
