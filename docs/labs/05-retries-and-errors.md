# Lab 5: Retries and error handling

**You'll build:** a workflow that calls an API that's down, retries it, and falls back cleanly
instead of failing.
**You'll learn:** retries with backoff, node timeouts, the three **On error** modes, and fail
fast.
**Needs:** nothing. **Time:** 15 minutes.

Real APIs time out, rate-limit you and go down. This lab shows how to make a workflow survive
that. The finished version is [`retry_and_errors.json`](../../examples/retry_and_errors.json).

## Steps

1. **Import** [`retry_and_errors.json`](../../examples/retry_and_errors.json) and **Save**. Its
   `url` variable points at `https://api.example.invalid/status`, an address that can never
   resolve.
2. Click **call_api** and open its **settings** tab:
   - **Retries (attempts):** `3`
   - **Backoff (s):** `1`, doubling after each attempt (1 s, then 2 s)
   - **On error:** *Continue on a separate "error" output*
3. Press **Run** and watch **This run** at the bottom. You'll see two `retry` lines, then the
   node fails, and **fallback** runs with the error message. The workflow as a whole still
   **succeeds**.
4. Look at the canvas: **call_api** has a second output, `error`, connected to **fallback**.
   The normal output goes to **success**.
5. Click the canvas and change the `url` variable to a working address:
   `https://api.open-meteo.com/v1/forecast?latitude=0&longitude=0&current=temperature_2m`.
   Run again. **success** runs and **fallback** is skipped.

## Try each error mode

Set the `url` back to the broken address and change **call_api**'s **On error** each time:

| On error | In the JSON | What happens |
|---|---|---|
| Stop the workflow | `stop` | The node fails and the whole run fails. Nothing after it runs. |
| Continue (error data on main output) | `continue` | `{"error": ...}` goes out of the normal output, so **success** runs with an error object. |
| Continue on a separate "error" output | `error_output` | `{"error": ...}` goes out of the `error` output only. Use this to build a fallback path. |

## Timeouts

1. Set **call_api**'s **Timeout (seconds)** to `1` and its `timeout` parameter (the HTTP
   timeout) to `30`. Point `url` at a slow endpoint, or keep the broken one. The node is cut off
   after 1 second per attempt.
2. Click the canvas: **Workflow settings** also has a timeout for the whole run.

## Check your work

- With the separate error output, the run is green even though **call_api** failed, and **fallback**'s
  output shows the reason.
- With *Stop the workflow*, the run is red and History shows which node failed.

## Challenges

- Send the fallback somewhere useful: add a Send Email node after **fallback** (after
  [lab 6](06-credentials-and-email.md)) to email yourself when the API is down.
- Build two independent branches from one trigger, make one fail, and compare runs with
  **Stop everything on the first unhandled failure** on and off in **Workflow settings**. With
  it off, the healthy branch finishes.
- Go back to your lab 3 workflow and give the HTTP node retries and an error output.

## What you learned

- Network errors, `429` and `5xx` responses are retried. Other `4xx` responses, bad parameters
  and missing credentials fail at once, because retrying wouldn't help.
- `error_output` turns a failure into data you can route, log or report.
- Failed background runs show a Windows notification and a red tray icon.

**Next:** [Lab 6: Credentials and email](06-credentials-and-email.md)
