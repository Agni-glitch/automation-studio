# Lab 6: Credentials and email

**You'll build:** your lab 3 weather workflow, extended to email you when the alert fires.
**You'll learn:** saving secrets as encrypted credentials, the Send Email node, and testing with
a dry run.
**Needs:** an email account that allows SMTP. These steps use Gmail. **Time:** 15 minutes.

## 1. Get an SMTP password

For Gmail, you need an **app password**, not your normal password:

1. Turn on 2-Step Verification for your Google account if it isn't on already.
2. Go to [App passwords](https://myaccount.google.com/apppasswords), create one named
   *Automation Studio*, and copy the 16-character password.

Other providers work the same way. Look up their SMTP host, port and whether they use
`starttls` (usually port 587) or `ssl` (usually port 465).

## 2. Save the credential

1. Choose **Credentials** in the top bar.
2. Pick the **SMTP email** type and name it `gmail`.
3. Fill in:

   | Field | Value |
   |---|---|
   | `host` | `smtp.gmail.com` |
   | `port` | `587` |
   | `username` | your Gmail address |
   | `password` | the app password |
   | `security` | `starttls` |
   | `from_address` | your Gmail address |

4. Choose **Save credential**. It's encrypted with a key that only your Windows account can
   use, and nodes refer to it by name only.

## 3. Send an email

1. Open your workflow from [lab 3](03-schedule-and-http.md) (or import
   [`weather_alert.json`](../../examples/weather_alert.json)).
2. Drag a **Send Email** node and connect the **alert** node's output to it.
3. On its **settings** tab, choose the `gmail` credential. On its **parameters** tab, set:
   - **To:** your email address
   - **Subject:** `Weather alert`
   - **Body:** `{{ input.message }}`
   - **Dry Run:** on
4. Click the canvas and lower `max_temp` below today's temperature, so the alert fires.
5. **Run**. Open the Send Email node's **output**: it shows the message it *would* send, with
   `"sent": false`.
6. Turn **Dry Run** off and run again. Check your inbox.
7. Set `max_temp` back to a sensible value and **Save**.

## Check your work

- The email arrives with the current temperature in the body.
- Look at **This run**: the log never shows your password. Credential values are always
  replaced with `***`.
- Export the workflow (**Export JSON**) and open the file. It contains `"gmail"`, the
  credential's name, but no password.

## Challenges

- Send an HTML email: turn **Html** on and set **Body** to `<h2>{{ input.message }}</h2>`.
- Add the `false` branch too, but only email when it's a Monday (use a Python node to check
  `datetime.date.today().weekday() == 0`, then an If node).
- Save the credential from the command line instead: `studio cred set gmail host port username
  password security from_address --type smtp`.

## What you learned

- Secrets belong in **Credentials**, never in node parameters or variables.
- **Dry Run** lets you check a message before anything is sent.
- A copied `data.db` is useless on another PC or Windows account, because the credentials can
  only be decrypted by yours.

**Next:** [Lab 7: Secure and public webhooks](07-secure-and-public-webhooks.md)
