# Security policy

Automation Studio runs workflows on your PC, stores credentials, and can expose webhooks to the
internet, so security reports are taken seriously.

## Supported versions

Only the latest release gets security fixes. The app checks for updates daily and installs
them after verifying their checksum.

## Reporting a vulnerability

**Please don't open a public issue.** Report it privately through GitHub instead:

1. Go to the repository's [**Security** tab](https://github.com/Agni-glitch/automation-studio/security).
2. Choose **Report a vulnerability**.

Include what you found, the steps to reproduce it, and the impact you expect. You should get a
reply within 7 days. Once a fix is released, the advisory will be published, with credit to you
unless you'd rather stay anonymous.

## What counts

The issues below are in scope:

- other websites or local users reaching the local API (`127.0.0.1:5680`) without the token;
- tunneled webhooks running workflows that weren't made public;
- getting around the Python Script sandbox's memory, process-count or timeout limits;
- credentials leaking into logs, execution history or the UI;
- the updater installing a file that fails its checksum or signature check.

These are working as intended:

- workflows doing what their author built them to do, such as a Python Script node reading
  files or using the network (the sandbox limits resources; it isn't an isolation boundary
  for untrusted code);
- anything that needs administrator access or an already compromised account.
