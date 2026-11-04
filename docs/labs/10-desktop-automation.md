# Lab 10: Desktop automation

**You'll build:** a workflow that opens Notepad, types a note and takes a screenshot.
**You'll learn:** opening apps, typing, pasting, key presses, hotkeys, screenshots and the
emergency stop.
**Needs:** a signed-in, unlocked Windows session. **Time:** 15 minutes.

Desktop automation controls your real mouse and keyboard. Use it for apps that have no API and
no web version. The finished version is
[`notepad_desktop.json`](../../examples/notepad_desktop.json).

## Safety first

- **Don't touch the mouse or keyboard** while a desktop step runs. You'd be typing into the
  same window.
- **To abort**, move the mouse quickly into any corner of the screen. The run stops at once.
- Only one desktop automation runs at a time, and it can't run while the PC is locked.

## Steps

1. **Import** [`notepad_desktop.json`](../../examples/notepad_desktop.json) and **Save**.
2. Click **notepad** and read the steps:
   ```json
   [
     { "action": "open", "target": "notepad" },
     { "action": "wait", "seconds": 2 },
     { "action": "type", "text": "{{ input.note }}" },
     { "action": "press", "key": "enter" },
     { "action": "paste", "text": "Run {{ execution.id }}" },
     { "action": "screenshot" }
   ]
   ```
3. Press **Run** and take your hands off the mouse. Notepad opens and the text appears.
4. Open the node's **output**. `screenshots` has the path of a full-screen screenshot.
5. Close Notepad without saving.

## Save the file with a hotkey

Add these steps before `screenshot` to save the note:

```json
{ "action": "hotkey", "keys": ["ctrl", "s"] },
{ "action": "wait", "seconds": 1.5 },
{ "action": "paste", "text": "studio-note.txt" },
{ "action": "press", "key": "enter" }
```

Run it. Notepad saves `studio-note.txt` in the folder its Save dialog opens, usually
**Documents**. (If the file already exists, Notepad asks whether to replace it, so delete it
between runs.)

## Check your work

- Notepad shows two lines: the note and the run id.
- Moving the mouse into a corner during a run stops it, and the run shows as failed.

## Challenges

- Use `activate_window` with the window title to switch to an app that's already open.
- Click on an image: take a small screenshot of a button, save it as a PNG, and use
  `{"action": "click", "image": "C:\\path\\button.png"}` so the click finds the button wherever
  it is on screen.
- `type` only handles plain ASCII characters. Use `paste` for anything else, such as accented
  letters or emoji.

## What you learned

- `open` starts an app by name or path, `type` and `paste` enter text, `press` and `hotkey`
  send keys, and `screenshot` records what happened.
- Add `wait` steps after anything that opens a window. Apps need a moment to appear.
- Prefer browser automation or an API when you can. Desktop steps break if a window moves or
  looks different.

**Next:** [Lab 11: Command line and version control](11-command-line.md)
