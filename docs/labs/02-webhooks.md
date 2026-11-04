# Lab 2: A webhook that replies

**You'll build:** a small local web API that greets whoever calls it.
**You'll learn:** webhook triggers, the `wait` response mode, Active workflows, the background
service and run history.
**Needs:** nothing. **Time:** 10 minutes.

## Steps

1. **Import** [`webhook_hello.json`](../../examples/webhook_hello.json) and **Save**.
2. Press **Run**. A manual run uses the webhook's **sample data**, so you can test it without
   calling it. **greet** runs with the name `manual run`.
3. Switch the workflow to **Active**. The app shows the address it's listening on.
4. In PowerShell, call it:
   ```powershell
   Invoke-RestMethod -Method Post http://127.0.0.1:5678/webhook/hello `
     -ContentType application/json -Body '{"name": "Ada"}'
   ```
   The reply is `{"message": "Hello Ada!", "execution": "..."}`. The webhook's
   **Response Mode** is `wait`, so it ran the whole workflow and returned the last node's output.
5. Send an empty body:
   ```powershell
   Invoke-RestMethod -Method Post http://127.0.0.1:5678/webhook/hello `
     -ContentType application/json -Body '{}'
   ```
   This time the If node sends it to **ask**, which tells the caller what to send.
6. **Close the app window.** Call the webhook again. It still answers, because Active workflows
   run in the background service. The tray icon (bottom right of the taskbar) shows it's running.
7. Open the app again and look at **History** at the bottom. Every call is there. Click one to
   see what each node did.

## Check your work

- Calling the webhook with your own name returns `Hello <your name>!`.
- History shows one run per call, including the ones made while the window was closed.

## Challenges

- Change the webhook's **Method** to `GET` and the `has_name` check to read
  `{{ input.query.name ?? "" }}`. Then open
  `http://127.0.0.1:5678/webhook/hello?name=Ada` in your browser.
- Change **Response Mode** to `immediate` and call it again. You get `202` and an execution id
  straight away, and the workflow finishes in the background. This suits slow workflows.
- Add a **Wait** node of 3 seconds before **greet** and see how long the call takes in `wait`
  mode.

## What you learned

- A webhook gives every workflow its own URL at `http://127.0.0.1:5678/webhook/<path>`.
- Webhook output has `method`, `path`, `query`, `headers` and `body`.
- **Active** workflows keep running after you close the window. Choose **Quit (stop background
  workflows)** in the tray menu to stop them all.

**Next:** [Lab 3: Scheduled API check](03-schedule-and-http.md)
