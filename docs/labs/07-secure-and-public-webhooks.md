# Lab 7: Secure and public webhooks

**You'll build:** a text-statistics API that only answers callers who know a secret token, and
then make it reachable from anywhere on the internet.
**You'll learn:** webhook token authentication, `response_node`, and the public tunnel.
**Needs:** an internet connection for part 2. **Time:** 20 minutes.

The finished version is [`secure_webhook.json`](../../examples/secure_webhook.json).

## Part 1: Require a token

1. Choose **Credentials**, pick the **Webhook shared secret** type, name it `webhook-token`, and
   set `token` to a long random value. To make one in PowerShell:
   ```powershell
   [Convert]::ToBase64String((1..32 | ForEach-Object { Get-Random -Maximum 256 }))
   ```
2. **Import** [`secure_webhook.json`](../../examples/secure_webhook.json) and **Save**. Click
   **hook** and note:
   - **Auth:** `header`, with **Auth Header** `X-Webhook-Token`
   - **Response Node:** `reply`, so the caller gets **reply**'s output
3. Press **Run** to test it with the sample text, then switch it to **Active**.
4. Call it **without** the token:
   ```powershell
   Invoke-RestMethod -Method Post http://127.0.0.1:5678/webhook/text-stats `
     -ContentType application/json -Body '{"text": "hello"}'
   ```
   You get `401` with `invalid or missing token`, and no run starts.
5. Call it **with** the token:
   ```powershell
   $token = "<your token>"
   Invoke-RestMethod -Method Post http://127.0.0.1:5678/webhook/text-stats `
     -Headers @{ "X-Webhook-Token" = $token } -ContentType application/json `
     -Body '{"text": "Automation Studio automates the boring parts of automation."}'
   ```
   You get the character count, word count and top words.

## Part 2: Reach it from the internet

1. Open **Settings → Public webhooks** and tick **Enable public tunnel**. The first time, the app
   downloads Cloudflare's `cloudflared`. After a few seconds you get an address like
   `https://some-random-words.trycloudflare.com`.
2. From another device, such as your phone on mobile data, or a service like
   [reqbin.com](https://reqbin.com), send the same POST to
   `https://<your address>/webhook/text-stats` with the `X-Webhook-Token` header.
3. Try the lab 2 workflow (`/webhook/hello`) through the tunnel. It replies `403`: webhooks
   without token auth only answer local calls unless you turn on **Allow Public** for them.
4. When you're done, untick **Enable public tunnel**.

## Check your work

- Without the token you get `401`. With it you get the statistics.
- Through the tunnel, `text-stats` works and `hello` returns `403`.

## Challenges

- Connect a real service: in a GitHub repository's **Settings → Webhooks**, point a webhook at
  your tunnel address with a workflow that logs `{{ input.body.action }}`. (GitHub sends its
  own signature header, so use **Allow Public** for this test, and turn it off afterwards.)
- Change **Response Mode** to `immediate` for slow work, and send the result by email instead.

## What you learned

- Token auth protects a webhook both locally and through the tunnel. Tokens are compared in
  constant time and never written to logs.
- The quick tunnel address changes every time the tunnel restarts. For a permanent address on
  your own domain, see [Stable tunnel URL](../architecture.md#public-webhooks).
- Only workflows you explicitly secure or mark public answer calls from the internet.

**Next:** [Lab 8: AI Agent](08-ai-agent.md)
