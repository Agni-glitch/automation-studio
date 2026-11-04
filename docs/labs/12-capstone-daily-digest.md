# Lab 12: Capstone: daily digest

**You'll build:** a workflow that runs every weekday at 8:00 without you: it scrapes the day's
headlines, has an AI pick the ones that match your interests, and emails you a short briefing.
**You'll learn:** combining a schedule, browser automation, AI with structured output, Python and
email into one dependable workflow.
**Needs:** labs 6, 8 and 9 done: a `gmail` credential, and Ollama with `llama3.2` (or an
Anthropic key). **Time:** 30 minutes.

The finished version is [`daily_digest.json`](../../examples/daily_digest.json).

## The plan

```
Schedule (weekdays 8:00)
  → Browser: scrape headlines
  → AI Agent: pick up to 5 that match your interests (validated JSON)
  → Python: format the email body
  → Send Email
```

## Steps

1. **Build it yourself first.** Using what you learned, create each node in the plan. Use cron
   `0 8 * * 1-5` for the schedule, the browser steps from [lab 9](09-browser-automation.md),
   and an output schema like:
   ```json
   {
     "type": "object",
     "required": ["picks"],
     "properties": {
       "picks": {
         "type": "array",
         "maxItems": 5,
         "items": {
           "type": "object",
           "required": ["headline", "why"],
           "properties": { "headline": { "type": "string" }, "why": { "type": "string" } }
         }
       }
     }
   }
   ```
2. **Or import** [`daily_digest.json`](../../examples/daily_digest.json) and compare it with
   yours.
3. Click the canvas and set **Variables**:
   - `interests`: what you care about, for example `"Python, security, space"`
   - `recipient`: your email address
   - `dry_run`: leave `true` for now
4. If you use Anthropic instead of Ollama, change **summarize**'s provider, model and credential.
5. **Run**. Check each node's output in turn: the headlines, the AI's picks, the formatted body,
   and the email that *would* be sent.
6. Set `dry_run` to `false`, run once more and check your inbox.
7. **Save**, switch to **Active**, and make sure the background service starts with Windows:
   **Settings → Background service → Start automatically when I sign in to Windows**.

## Make it dependable

An unattended workflow should survive a bad morning. Check that yours has:

- **Retries** on the browser and AI nodes (the example uses 2 attempts each).
- **Timeouts**: a longer `timeout_ms` on the `goto` step for slow networks, and a workflow
  timeout in **Workflow settings**.
- **An error path**: set **scrape**'s **On error** to *Continue on a separate "error" output* and connect its `error`
  output to a second Send Email node that tells you the digest failed
  ([lab 5](05-retries-and-errors.md)).

## Check your work

- A manual run with `dry_run` on shows a sensible email body with up to five picks.
- The next weekday at 8:00, the email arrives without you opening the app. History shows the run.

## Make it yours

- Scrape a different source: a news site, a forum, your company's status page.
- Add a second source in a parallel branch and merge both lists in the Python node (it receives
  every upstream output in `inputs`).
- Instead of email, POST the digest to a chat tool's incoming webhook with an HTTP Request node.
- Save each day's picks to a file with a Python node to build up an archive.

## What you learned

You've used every part of Automation Studio: triggers, actions, AI, code, logic, credentials,
error handling and the background service. Next, look through the [node reference](../nodes.md)
for anything you haven't tried, and share what you build. Example workflows are welcome
contributions: see [CONTRIBUTING.md](../../CONTRIBUTING.md).
