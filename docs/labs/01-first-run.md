# Lab 1: Your first run

**You'll build:** nothing yet. You'll import a small candidate-screening workflow, run it, and
change it to see how data flows between nodes.
**You'll learn:** the editor layout, running a workflow, reading outputs, `{{ expressions }}`,
If branches, parallel branches and workflow variables.
**Needs:** nothing. **Time:** 10 minutes.

## Steps

1. Open Automation Studio. Look at the four areas:
   - **Left:** your saved workflows and the node palette.
   - **Middle:** the canvas.
   - **Right:** the selected node's **parameters**, **settings** and **output**.
   - **Bottom:** logs and run history.
2. Choose **Import**, pick [`hello_workflow.json`](../../examples/hello_workflow.json), then
   **Save**.
3. Press **Run**. Watch each node change color as it runs. When it finishes, **reject** is grey
   because it was skipped.
4. Click **start** and open its **output** tab. You'll see the trigger's sample data:
   `{"candidate": "Ada Lovelace", "score": 82}`.
5. Click **check** (the If node) and look at its **parameters**:
   - `left` is `{{ nodes.start.score }}`, the score from the **start** node.
   - `right` is `{{ vars.threshold }}`, a workflow variable.
   82 is at least 70, so the `true` output fired and **shortlist** ran.
6. Notice that **greet** and **pause** both start from **start** and run at the same time.
   **check** waits until both have finished. This is a parallel branch.

## Change it

1. Click an empty part of the canvas to open **Workflow settings**. Under **Variables**, change
   `threshold` from `70` to `90`. Run again. This time **reject** runs and **shortlist** is
   skipped.
2. Click **greet** and change its message to:
   ```
   Hi {{ input.candidate }}, your score is {{ input.score }}
   ```
   Run it and check **greet**'s output.
3. Click **start** and remove `"candidate"` from its sample data. Run again. **greet** fails
   because the field is missing. Now change the message to use a fallback:
   ```
   Hi {{ input.candidate ?? "friend" }}
   ```
   and run again. It works.

## Check your work

- With `threshold` at 90, **reject**'s output is `{"decision": "reject", "who": "Ada Lovelace"}`.
- The **History** tab at the bottom lists every run you did, with its status.

## Challenges

- Add a third outcome: a second If node after **check**'s `false` output that sends scores of
  50 or more to a new **waitlist** Set node.
- Use `"include_input": true` on **shortlist** so its output keeps the original fields as well
  as `decision`.

## What you learned

- `{{ input.x }}` reads the previous node's output, `{{ nodes.<id>.x }}` reads any earlier
  node, and `{{ vars.x }}` reads a workflow variable.
- `??` gives a fallback when a field might be missing.
- A node runs when all of its predecessors have finished, and only if a branch leading to it
  fired.

**Next:** [Lab 2: A webhook that replies](02-webhooks.md)
