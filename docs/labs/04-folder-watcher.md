# Lab 4: Folder sorter

**You'll build:** a folder that tidies itself. Drop a file in, and it's moved into a subfolder
for its type: `PDFs`, `Images`, `Documents`, `Archives` or `Other`.
**You'll learn:** Folder Watcher triggers, working with files in a Python Script, and script
arguments.
**Needs:** nothing. **Time:** 15 minutes.

The finished version is [`folder_sorter.json`](../../examples/folder_sorter.json).

## Steps

1. In File Explorer, create the folder `Documents\Sort Me`.
2. **Import** [`folder_sorter.json`](../../examples/folder_sorter.json) and **Save**. Click the
   canvas and check the `folder` variable: `%USERPROFILE%\Documents\Sort Me`. Change it if you
   used a different folder.
3. Click **new_file** (the Folder Watcher) and look at its parameters:
   - **Patterns:** `["*"]` means every file.
   - **Events:** `["created"]` means only new files.
   - **Settle Seconds:** `2` means it waits until a file has stopped growing for 2 seconds, so a
     large download isn't picked up half-written.
4. Click **move** and read the script. It reads the extension, picks a group from
   `args["groups"]` (set in the node's **Arguments**), creates the subfolder and moves the file.
   If a file with that name is already there, it adds ` (1)`, ` (2)` and so on.
5. Switch the workflow to **Active**.
6. Copy a PDF, an image and a `.txt` file into `Sort Me`. Within a few seconds each one moves
   into its subfolder.
7. Open **All activity** at the bottom to see each run's log line, such as
   `Moved invoice.pdf -> PDFs`.

## Check your work

- `Sort Me` now contains only subfolders, and every file is in the right one.
- Dropping the same file twice gives `name.pdf` and `name (1).pdf`.

## Challenges

- Add a `Videos` group for `.mp4` and `.mov` by editing **Arguments**. No code change is needed.
- Sort by date instead of type: create subfolders such as `2026-11` from the file's modified time
  (`Path(...).stat().st_mtime`).
- Point the `folder` variable at your real `Downloads` folder. Set **Ignore Patterns** so
  partial downloads are skipped (the defaults already ignore `*.crdownload`, `*.part` and
  `*.tmp`).

## What you learned

- Folder Watcher output is `{event, path, name, stem, extension, directory, size}`.
- Folder paths can use environment variables such as `%USERPROFILE%`.
- Script **Arguments** keep settings out of the code, available as `args`.
- The watcher ignores subfolders unless **Recursive** is on, so files the workflow moves don't
  trigger it again.

**Next:** [Lab 5: Retries and error handling](05-retries-and-errors.md)
