# Command line

The installed app includes `studio.exe`, a command-line tool in the install folder
(`%LOCALAPPDATA%\Programs\AutomationStudio`). From a source checkout, run `python main.py`
with the same arguments. Every command accepts `--db <path>` to use a database other than
`%LOCALAPPDATA%\AutomationEngine\data.db`, and `--help` for details.

## Run workflows

```powershell
studio run examples\hello_workflow.json                    # run a file once
studio run examples\webhook_hello.json --trigger '{"body": {"name": "Ada"}}'
studio run job-pipeline                                    # a saved workflow, by id
studio run flow.json --no-db                               # no credentials, no history
```

## Manage saved workflows

```powershell
studio wf import examples\webhook_hello.json --activate    # save (or update) and arm its triggers
studio wf list
studio wf activate webhook-hello
studio wf deactivate webhook-hello
studio history                                             # recent runs
studio history --workflow webhook-hello --limit 50
studio history --show <execution-id>                       # one run, node by node
```

A running service picks up imports, activations and edits within a few seconds.

## Credentials

```powershell
studio cred set anthropic api_key                          # prompts for each value, hidden
studio cred set gmail host port username password security from_address --type smtp
studio cred list                                           # names and fields only, never values
studio cred delete gmail
```

## Background service

```powershell
studio status                       # service, tunnel, autostart, active workflows
studio stop                         # stop the service and all background workflows
studio open                         # open the window (starts the service if needed)
studio autostart on|off|status      # start the service when you sign in
studio tunnel on|off|status         # public HTTPS URL for webhooks
studio tunnel on --mode token --credential cf-tunnel --hostname hooks.example.com
studio update status|check|install
```

`studio serve` runs the service in the foreground, which is useful for watching events:

| Option | Meaning |
|---|---|
| `-v`, `--verbose` | print every execution event |
| `--port`, `--api-port` | webhook port (default 5678) and API port (default 5680) |
| `--host` | webhook listen address (default `127.0.0.1`) |
| `--background` | log to file only; this is how sign-in startup runs it |
| `--tray`, `--no-tray` | show or hide the tray icon (shown by default with `--background`) |
| `--dev` | accept the Vite dev server on port 5173 (frontend development) |

Only one service runs at a time; a second `serve` exits with a message.
