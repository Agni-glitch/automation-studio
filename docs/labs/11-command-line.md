# Lab 11: Command line and version control

**You'll build:** a folder of workflows kept in Git, imported and run from PowerShell.
**You'll learn:** the `studio` command, running workflows from scripts, importing and
activating, reading history, and keeping workflows under version control.
**Needs:** nothing (Git is optional). **Time:** 15 minutes.

Full details are in the [command line reference](../cli.md).

## 1. Find `studio`

`studio.exe` is in the install folder. Add it to this PowerShell session:

```powershell
$env:Path += ";$env:LOCALAPPDATA\Programs\AutomationStudio"
studio status
```

`studio status` shows whether the background service is running, the tunnel, autostart and
your active workflows.

## 2. Run workflows from the command line

```powershell
studio wf list                                           # saved workflows and their ids
studio run webhook-hello --trigger '{"body": {"name": "CLI"}}'
studio run examples\hello_workflow.json --no-db          # a file, without saving history
```

Every event is printed as it happens, the same events you see in the editor's log.

## 3. Import, activate and inspect

```powershell
studio wf import examples\weather_alert.json --activate
studio history --workflow weather-alert --limit 5
studio history --show <execution-id>                     # one run, node by node
studio wf deactivate weather-alert
```

The running service picks up imports and activations within a few seconds. Open the editor and
you'll see the change.

## 4. Keep workflows in Git

1. In the editor, open each workflow you built in these labs and choose **Export JSON**. Save
   them all in one folder, such as `Documents\my-automations`.
2. Put the folder under version control:
   ```powershell
   cd $env:USERPROFILE\Documents\my-automations
   git init
   git add .
   git commit -m "My first automations"
   ```
3. Change a workflow in the editor, export it again over the old file, and run `git diff` to see
   exactly what changed.
4. To restore or move a workflow to another PC, run `studio wf import <file>`. Credentials
   aren't in the files, so recreate them on the new PC with the same names.

## Check your work

- `studio wf list` shows the workflows from the earlier labs.
- `git log` in your automations folder shows your commit.

## Challenges

- Write a `deploy.ps1` that imports and activates every `.json` file in the folder:
  ```powershell
  Get-ChildItem *.json | ForEach-Object { studio wf import $_.FullName --activate }
  ```
- Use `studio run` from Windows Task Scheduler or another script to start a workflow as one step
  of a bigger job.
- Run `studio serve -v` in a terminal (after `studio stop`) to watch every background event live.

## What you learned

- Anything you can do in the editor, you can script with `studio`.
- Workflow files never contain secrets, so they're safe to commit and share.
- Each workflow's `id` is its stable name for the CLI and for imports. Importing a file with an
  existing id updates that workflow.

**Next:** [Lab 12: Capstone: daily digest](12-capstone-daily-digest.md)
