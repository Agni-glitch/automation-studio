# Nodes and workflows

A workflow is a graph of **nodes**. Triggers start it; every other node receives the output of
the nodes connected to its input and produces an output of its own. This page lists every
built-in node and explains how a workflow runs.

Parameters marked **\*** are required. Any text parameter can contain
[`{{ expressions }}`](#expressions).

## Triggers

### Manual Trigger · `trigger.manual`
Starts the workflow when you press **Run** (or `studio run`).
- `sample_data`: the output used for a manual run.

### Webhook · `trigger.webhook`
Starts the workflow on an HTTP request to `http://127.0.0.1:5678/webhook/<path>`.
Output: `{method, path, query, headers, body, client}`.
- `path`\*: the URL path after `/webhook/`.
- `method`: `GET`, `POST` (default), `PUT`, `PATCH` or `DELETE`.
- `auth`: `none` or `header`. With `header`, callers must send the credential's `token` in the
  `auth_header` header (default `X-Webhook-Token`).
- `response_mode`: `immediate` replies `202` with the execution id at once; `wait` runs the workflow and replies with
  the output of `response_node` (or the last node), waiting up to `wait_timeout` seconds.
- `allow_public`: accept calls arriving through the [public tunnel](getting-started.md#public-webhooks)
  without token auth. Off by default.

### Folder Watcher · `trigger.file`
Starts the workflow when files change in a folder. It waits until a file stops growing
(`settle_seconds`) before firing, ignores temporary and partial downloads, and treats a rename
into place as `created`. Output: `{event, path, name, stem, extension, directory, size, src_path}`.
- `directory`\*: the folder to watch; may use `{{ vars.x }}`.
- `patterns`: file patterns such as `["*.pdf", "*.docx"]` (all files if empty).
- `ignore_patterns`: patterns to skip.
- `events`: any of `created`, `modified`, `deleted`, `moved`.
- `recursive`: include subfolders.

### Schedule · `trigger.schedule`
Starts the workflow on a schedule, in local time. Runs missed while the app was closed are not
caught up. Output: `{scheduled_for, fired_at}`.
- `mode`: `cron` or `interval`.
- `cron`: five fields, for example `0 9 * * 1-5` (9:00 on weekdays) or `*/15 * * * *`.
- `every_seconds`: the interval for `interval` mode.
- `run_on_start`: also run once when the workflow is activated.
- `skip_if_running`: skip a run while the previous one is still going (on by default).

## AI

### AI Agent · `ai.agent`
Sends a prompt to a language model. Output: `{result, text, model, usage}`.
- `provider`: `anthropic`, `openai` or `ollama`.
- `model`\*: the provider's model id, for example `claude-sonnet-5-5`.
- `prompt`\*, `system_prompt`: the instructions.
- `input_data`: data to include with the prompt, usually an expression such as `{{ input }}`.
- `output_schema`: a JSON Schema. The reply is validated against it and returned as JSON in
  `result`. A reply that doesn't match is retried.
- `temperature`, `max_tokens` (default 2048), `request_timeout` (default 120 s).
- `base_url`: for OpenAI-compatible servers or a non-default Ollama address.
- Credential: `{api_key}` (not needed for a local Ollama).

## Code

### Python Script · `code.python`
Runs Python in a separate process. Inside the script, `input` is the upstream output, `inputs`
is every upstream output by node id, `args` is the `arguments` parameter, and `log(...)` (or
`print`) writes to the run log. Either define `main(input)` and return a value, or assign
`result = ...`. The result must be JSON-serializable.

```python
def main(input):
    jobs = [j for j in input["data"] if "python" in j["title"].lower()]
    log(f"{len(jobs)} matching jobs")
    return {"jobs": jobs}
```

- `code`\*, `arguments`.
- `timeout_seconds` (default 30), `memory_limit_mb` (default 512).

The script can't start other processes and gets a stripped environment and a temporary working
folder. It can still read files and use the network, so only run scripts you trust. The
packaged app bundles Python's standard library; third-party packages aren't available there.

## Actions

### HTTP Request · `action.http_request`
Calls a web API. Output: `{status, headers, data}`.
- `method`, `url`\*, `query`, `headers`, and `json_body` or `body`.
- `auth`: `none`, `bearer` (`{token}`), `api_key_header` or `api_key_query` (`{api_key}` sent as
  `auth_key_name`), or `basic` (`{username, password}`).
- `response_format`: `auto`, `json` or `text`.
- `fail_on_error_status` (on by default): 429 and 5xx responses and network errors are retried;
  other 4xx responses fail immediately.
- `timeout` (default 30 s), `follow_redirects`.

### Send Email · `action.email`
Sends an email over SMTP.
- `to`\*, `cc`, `bcc`, `subject`\*, `body`\*, `html`, `from_address`, `reply_to`.
- `dry_run`: build the message without sending it.
- Credential: `{host, port, username, password, security: starttls|ssl|none, from_address}`.

### Social Post · `action.social_post`
Publishes a text post on LinkedIn. **Dry run is on by default.**
- `text`\*, `visibility` (`PUBLIC` or `CONNECTIONS`), `api_version` (a currently supported
  LinkedIn API version).
- Credential: `{access_token, author_urn}`; the token needs the `w_member_social` scope.

### Browser Automation · `action.browser`
Drives a real browser through a list of steps with Playwright. Output: `{url, title, data, screenshots}`.
- `steps`\*: a list such as
  ```json
  [{"action": "goto", "url": "https://example.com"},
   {"action": "fill", "selector": "#q", "value": "{{ input.query }}"},
   {"action": "press", "selector": "#q", "value": "Enter"},
   {"action": "extract_all_text", "selector": ".result h3", "name": "titles"}]
  ```
  Actions: `goto`, `click`, `fill`, `type`, `press`, `select`, `check`, `uncheck`, `hover`,
  `wait_for`, `wait`, `extract_text`, `extract_all_text`, `extract_html`, `extract_attribute`, `screenshot`,
  `evaluate`. Extract and evaluate steps store their result in `data` under `name`.
- `browser`: `msedge` (default) or `chrome`, both using the browser already installed. When
  running from source with Playwright's own browsers installed, `chromium`, `firefox` and
  `webkit` also work.
- `headless` (on by default), `profile_dir` (keeps logins between runs), `viewport_width`,
  `viewport_height`, `screenshot_dir`.

### Desktop Automation · `action.desktop`
Controls the Windows desktop with PyAutoGUI. Output: `{data, screenshots}`. Needs a signed-in,
unlocked session. Moving the mouse into a screen corner aborts the run.
- `steps`\*: actions `open`, `activate_window`, `hotkey`, `press`, `type` (ASCII), `paste` (any
  text), `click`, `double_click`, `right_click` (coordinates or an image to find), `move`,
  `scroll`, `screenshot`, `locate_image`.
- `pause_between_actions` (default 0.2 s), `screenshot_dir`.

Only one desktop automation runs at a time.

## Logic

### If · `logic.if`
Sends its input to the `true` or `false` output.
- `left`, `operator`, `right`. Operators: `equals`, `not_equals`, `greater_than`,
  `greater_or_equal`, `less_than`, `less_or_equal`, `contains`, `not_contains`, `starts_with`,
  `ends_with`, `matches_regex`, `is_empty`, `is_not_empty`, `is_true`, `is_false`.

### Set Fields · `logic.set`
Builds an object from fixed values and expressions.
- `values`: for example `{"message": "Hello {{ input.body.name }}!"}`.
- `include_input`: merge the values into the input instead of replacing it.

### Wait · `logic.wait`
Pauses for `seconds`, then passes its input on unchanged.

## Expressions

Text parameters can read data with `{{ path }}`. Expressions only look values up; they never run
code.

| Expression | Value |
|---|---|
| `{{ input }}`, `{{ input.items[0].id }}` | the input: the upstream node's output, or `{node_id: output}` when several nodes connect in |
| `{{ nodes.fetch.data }}` | the output of an earlier node, by id |
| `{{ trigger.body }}` | the data the workflow started with |
| `{{ vars.threshold }}` | a workflow variable |
| `{{ execution.id }}` | the current run's id |
| `{{ input.name ?? "friend" }}` | a fallback when the path is missing (a literal or another path) |

A missing path is an error unless it has a `??` fallback. Only nodes **upstream** of the current
one are visible, so a result never depends on timing. A parameter that is exactly one expression
keeps the value's type (a number stays a number); an expression inside other text becomes a
string.

## How a workflow runs

| Topic | Behavior |
|---|---|
| Order | A node starts as soon as **all** its predecessors have finished. Independent branches run in parallel, up to `max_concurrency` at a time. |
| Branching | A node runs only if at least one incoming connection's output fired. Otherwise it's `skipped`, and so is everything after it. |
| Retries | `retry.max_attempts` with exponential backoff (`backoff_seconds`). Bad parameters, a missing credential or a bad expression fail at once without retrying. |
| Errors | `on_error`: `stop` fails the workflow; `continue` passes `{"error": ...}` on to the next node; `error_output` sends `{"error": ...}` to the node's `error` output instead. |
| Fail fast | With `fail_fast: true` (default), the first unhandled failure cancels the other running branches. With `false`, independent branches finish. |
| Timeouts | Per node (`timeout_seconds`, default 300) and per workflow (`settings.timeout_seconds`). |
| Secrets | Credential values are replaced with `***` in logs and error messages. |

## Workflow JSON

The editor saves workflows as JSON, which you can export, keep in version control and import
again (or import with `studio wf import`).

```json
{
  "name": "Job screening",
  "variables": { "threshold": 70 },
  "settings": { "max_concurrency": 4, "timeout_seconds": 600, "fail_fast": true },
  "nodes": [
    { "id": "start", "type": "trigger.manual" },
    { "id": "fetch", "type": "action.http_request",
      "parameters": { "url": "https://api.example.com/jobs", "auth": "bearer" },
      "credentials": { "default": "jobs-api" },
      "retry": { "max_attempts": 3, "backoff_seconds": 2 },
      "timeout_seconds": 30, "on_error": "stop" },
    { "id": "check", "type": "logic.if",
      "parameters": { "left": "{{ nodes.fetch.data.count }}", "operator": "greater_than", "right": 0 } },
    { "id": "notify", "type": "action.email",
      "parameters": { "to": "me@example.com", "subject": "New jobs", "body": "{{ nodes.fetch.data.count }} new" },
      "credentials": { "default": "gmail" } }
  ],
  "connections": [
    { "source": "start", "target": "fetch" },
    { "source": "fetch", "target": "check" },
    { "source": "check", "target": "notify", "source_output": "true" }
  ]
}
```

`credentials` maps a node's credential slot to the **name** of a saved credential; the secret
itself is never in the file. The [examples](../examples) folder has complete workflows:

| File | What it shows |
|---|---|
| [`webhook_hello.json`](../examples/webhook_hello.json) | webhook that waits and replies, If routing; no keys needed |
| [`hello_workflow.json`](../examples/hello_workflow.json) | parallel branches and If routing |
| [`cv_inbox.json`](../examples/cv_inbox.json) | folder watcher → read a CV → AI summary → write a `.analysis.json` file |
| [`job_pipeline.json`](../examples/job_pipeline.json) | fetch jobs → clean them in Python → AI match against a CV → email the shortlist |
| [`weather_alert.json`](../examples/weather_alert.json) | interval schedule → public API (no key) → Python → If alert |
| [`folder_sorter.json`](../examples/folder_sorter.json) | folder watcher → Python moves each file into a subfolder for its type |
| [`retry_and_errors.json`](../examples/retry_and_errors.json) | retries with backoff, then an `error` output that routes to a fallback |
| [`secure_webhook.json`](../examples/secure_webhook.json) | webhook with token auth that replies with text statistics |
| [`hn_headlines.json`](../examples/hn_headlines.json) | browser automation: extract headlines and a link, take a screenshot |
| [`notepad_desktop.json`](../examples/notepad_desktop.json) | desktop automation: open Notepad, type, paste, screenshot |
| [`daily_digest.json`](../examples/daily_digest.json) | weekday cron → scrape headlines → local AI picks → email (dry run by default) |

The [hands-on labs](labs/README.md) walk through each of these step by step.
