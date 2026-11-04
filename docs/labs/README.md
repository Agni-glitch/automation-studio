# Hands-on labs

Twelve short, practical exercises that take you from your first run to a complete automation
that runs every morning on its own. Each lab builds one real workflow and introduces one or two
new features. Do them in order the first time; later labs assume you know the earlier ones.

Every lab follows the same shape: **what you'll build**, **steps**, **check your work**, and
**challenges** to try on your own. Each one has a finished workflow in the
[`examples`](../../examples) folder you can import to compare with your version or to skip ahead.

## Before you start

- Install Automation Studio ([Getting started](../getting-started.md#install)) and open it once.
- Download the [`examples`](../../examples) folder from this repository, or download single
  files as each lab needs them (open the file on GitHub and choose **Download raw file**).
- Keep a PowerShell window handy. Several labs call workflows from it.

## The labs

| # | Lab | You'll learn | Needs | Time |
|---|---|---|---|---|
| 1 | [Your first run](01-first-run.md) | the editor, running, outputs, expressions, If branches, variables | nothing | 10 min |
| 2 | [A webhook that replies](02-webhooks.md) | webhook triggers, Active workflows, the background service, history | nothing | 10 min |
| 3 | [Scheduled API check](03-schedule-and-http.md) | building from scratch, Schedule, HTTP Request, Python Script | internet | 20 min |
| 4 | [Folder sorter](04-folder-watcher.md) | Folder Watcher, working with files in Python, script arguments | nothing | 15 min |
| 5 | [Retries and error handling](05-retries-and-errors.md) | retries with backoff, timeouts, error outputs, fail fast | nothing | 15 min |
| 6 | [Credentials and email](06-credentials-and-email.md) | encrypted credentials, Send Email, dry runs | an email account | 15 min |
| 7 | [Secure and public webhooks](07-secure-and-public-webhooks.md) | token auth, the public tunnel, calling your PC from the internet | internet | 20 min |
| 8 | [AI Agent](08-ai-agent.md) | AI Agent node, Ollama or Anthropic, structured output with JSON Schema | Ollama or an API key | 25 min |
| 9 | [Browser automation](09-browser-automation.md) | driving Edge, selectors, extracting data, screenshots, logins | Microsoft Edge | 20 min |
| 10 | [Desktop automation](10-desktop-automation.md) | opening apps, typing, hotkeys, screenshots, safety | an unlocked session | 15 min |
| 11 | [Command line and version control](11-command-line.md) | `studio` commands, export and import, keeping workflows in Git | nothing | 15 min |
| 12 | [Capstone: daily digest](12-capstone-daily-digest.md) | combining everything into one unattended workflow | labs 6, 8 and 9 | 30 min |

Labs 1 to 5 need no accounts or keys, so you can do them in one sitting.

## Examples used in the labs

| Lab | Example |
|---|---|
| 1 | [`hello_workflow.json`](../../examples/hello_workflow.json) |
| 2 | [`webhook_hello.json`](../../examples/webhook_hello.json) |
| 3 | [`weather_alert.json`](../../examples/weather_alert.json) |
| 4 | [`folder_sorter.json`](../../examples/folder_sorter.json) |
| 5 | [`retry_and_errors.json`](../../examples/retry_and_errors.json) |
| 6 | your workflow from lab 3, plus a Send Email node |
| 7 | [`secure_webhook.json`](../../examples/secure_webhook.json) |
| 8 | [`cv_inbox.json`](../../examples/cv_inbox.json), [`job_pipeline.json`](../../examples/job_pipeline.json) |
| 9 | [`hn_headlines.json`](../../examples/hn_headlines.json) |
| 10 | [`notepad_desktop.json`](../../examples/notepad_desktop.json) |
| 12 | [`daily_digest.json`](../../examples/daily_digest.json) |

## Tips for every lab

- **Save often** with `Ctrl+S`, and run with `Ctrl+Enter`.
- **Click a node, then its Output tab**, to see exactly what it produced. Most mistakes become
  obvious there, such as a field named differently from what you expected.
- **Click the empty canvas** to open **Workflow settings**, where you edit the workflow's
  description and **Variables**.
- **Read the bottom panel.** **This run** shows the live log, **All activity** shows background
  runs, and **History** keeps every past run.
- **Turn workflows off when you're done.** Switch practice workflows back to **Inactive** so
  they stop listening in the background.

Stuck? The [node reference](../nodes.md) lists every parameter, and you can
[open an issue](https://github.com/Agni-glitch/automation-studio/issues) if something doesn't
behave the way a lab says.
