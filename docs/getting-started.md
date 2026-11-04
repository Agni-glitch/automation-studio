# Getting started

This guide walks through installing Automation Studio, building a workflow, and running it in
the background. For every node's settings, see [Nodes and workflows](nodes.md). To practise
with real workflows, step by step, try the [hands-on labs](labs/README.md).

## Install

Download the installer from the [latest release](https://github.com/Agni-glitch/automation-studio/releases/latest)
and run it. It installs per-user into `%LOCALAPPDATA%\Programs\AutomationStudio` without an
administrator prompt. The installer offers two options:

- **Create a desktop shortcut** (on by default). A Start menu shortcut is always created.
- **Run in the background when I sign in.** Your active workflows keep listening after a restart.
  You can change this later in Settings.

Windows may warn that the app is from an unknown publisher, because it isn't code-signed yet.
Choose **More info → Run anyway**.

**Portable zip:** unzip it anywhere and run `AutomationStudio.exe`. It works the same but
doesn't update itself: download the new zip when a release comes out.

**Uninstalling** (Settings → Apps) removes the program and keeps your data in
`%LOCALAPPDATA%\AutomationEngine`. Delete that folder too if you want a clean slate.

## The editor

- **Left:** your saved workflows, and the node palette. Drag a node onto the canvas.
- **Canvas:** connect a node's output (right side) to another node's input (left side). An
  If node has `true` and `false` outputs.
- **Right:** the selected node's **Parameters**, its **Settings** (retries, timeout, error
  handling), and its **Output** from the last run.
- **Bottom:** live logs for this run, all activity, and run history.
- **Top bar:** Save, Run, the Active switch, Credentials and Settings.

Press **Run** to run the workflow once. Triggers use their *sample data* for manual runs, so you
can test a webhook workflow without calling it.

## Pass data between steps

Text fields accept `{{ expressions }}` that read data from earlier steps:

| Expression | Value |
|---|---|
| `{{ input.body.name }}` | a field of the previous node's output |
| `{{ nodes.fetch.data[0].title }}` | a field of any earlier node, by its id |
| `{{ trigger.path }}` | the trigger's data |
| `{{ vars.threshold }}` | a workflow variable |
| `{{ input.name ?? "friend" }}` | a fallback when the field is missing |

Expressions only look values up, they never run code. A field that is just one expression keeps
its type (a number stays a number); mixed text produces a string.

## Credentials

API keys and passwords go in **Credentials**, never in node parameters. They're encrypted with
a key that Windows protects for your user account, so a copied database is useless on another
PC or account. Nodes refer to a credential by name, and its values are masked as `***` in logs.

| Node | Fields |
|---|---|
| AI Agent | `api_key` (not needed for Ollama) |
| HTTP Request | `token`, `api_key`, or `username` + `password` |
| Send Email | `host`, `port`, `username`, `password`, `security`, `from_address` |
| Social Post | `access_token`, `author_urn` |

For Gmail, use `smtp.gmail.com`, port 587, `starttls`, and an
[app password](https://support.google.com/accounts/answer/185833).

## AI models

The AI Agent node calls the provider directly:

- **Anthropic:** model such as `claude-sonnet-5-5`, with an `api_key` credential.
- **OpenAI:** model such as `gpt-5`, with an `api_key` credential. Set `base_url` to use any
  OpenAI-compatible server.
- **Ollama:** install [Ollama](https://ollama.com), pull a model (`ollama pull llama3.2`), and
  use provider `ollama`. No key or internet connection needed.

Give the node an **Output Schema** (JSON Schema) to get validated JSON back in `result`, ready for
If nodes and later steps.

## Run workflows in the background

Switch a workflow to **Active** to arm its triggers:

| Trigger | Runs when |
|---|---|
| Webhook | an HTTP request arrives at `http://127.0.0.1:5678/webhook/<path>` |
| Folder Watcher | files matching a pattern are created, changed, renamed or deleted (after they finish writing) |
| Schedule | a cron expression (local time) or interval comes due |
| Manual | you press Run |

Active workflows run in the **background service**, which keeps going when you close the window.
Its tray icon shows a green dot when everything is fine, amber when an update is available, and
red when a trigger or the tunnel has a problem. Failed background runs show a Windows
notification. Choose **Quit (stop background workflows)** in the tray menu to stop everything.

To start the service when you sign in, open **Settings → Background service** and tick
**Start automatically when I sign in to Windows**, or run `studio autostart on`.

## Public webhooks

Webhooks only listen on your PC. To receive calls from the internet (a form, GitHub, Stripe),
open **Settings → Public webhooks** and tick **Enable public tunnel**. The app downloads Cloudflare's `cloudflared` and gives you a
random `https://<words>.trycloudflare.com` address. It needs no account, but it changes every
time the tunnel restarts.

Only webhooks that use token authentication or have **Allow Public** turned on answer calls
that come through the tunnel; others reply 403. For a permanent address on your own domain, see
[Stable tunnel URL](architecture.md#public-webhooks).

## Updates

The app checks this repository for a new release once a day and shows a **↑ vX** pill when one
is available. **Install update** downloads the installer and only runs it if its SHA-256 matches
the checksum GitHub publishes. It then upgrades silently and reopens the app. You can turn
automatic checks off in **Settings → Updates**.

## Where things are stored

| What | Where |
|---|---|
| Workflows, history, credentials | `%LOCALAPPDATA%\AutomationEngine\data.db` (credentials encrypted) |
| Encryption key (protected by Windows) | `%LOCALAPPDATA%\AutomationEngine\data.key` |
| Logs | `%LOCALAPPDATA%\AutomationEngine\logs\service.log` |
| Downloaded helpers (`cloudflared`) | `%LOCALAPPDATA%\AutomationEngine\bin` |

Back up `data.db` and `data.key` together to keep your workflows. Credentials can only be
decrypted by the same Windows account.
