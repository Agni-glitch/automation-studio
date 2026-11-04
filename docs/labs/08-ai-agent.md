# Lab 8: AI Agent

**You'll build:** an inbox folder that reads every CV you drop into it and writes a structured
profile next to it.
**You'll learn:** the AI Agent node with a local or hosted model, prompts and input data, and
validated JSON output with an output schema.
**Needs:** either [Ollama](https://ollama.com) (free, runs locally, no key) or an Anthropic or
OpenAI API key. **Time:** 25 minutes.

## 1. Choose a model

**Option A: Ollama (free and private).**
1. Install Ollama from [ollama.com](https://ollama.com).
2. In PowerShell, run `ollama pull llama3.2`. It downloads about 2 GB once.
3. In the AI Agent node, use **Provider** `ollama` and **Model** `llama3.2`. No credential is
   needed.

**Option B: Anthropic.**
1. Create an API key in the [Anthropic Console](https://console.anthropic.com).
2. Choose **Credentials**, pick the **API key** type, name it `anthropic`, and paste the key into
   `api_key`.
3. In the AI Agent node, use **Provider** `anthropic` and **Model** `claude-sonnet-5-5`, and
   choose the `anthropic` credential on its **settings** tab.

(OpenAI works the same way with provider `openai`. Set **Base Url** to use any
OpenAI-compatible server.)

## 2. Try a prompt

1. Choose **+ New**. Add a **Manual Trigger** with sample data
   `{"review": "Arrived late and the box was crushed, but support refunded me in an hour."}`.
2. Add an **AI Agent** node after it with your provider and model, and:
   - **Prompt:** `Classify this customer review.`
   - **Input Data:** `{{ input.review }}`
   - **Output Schema:**
     ```json
     {
       "type": "object",
       "required": ["sentiment", "topics"],
       "properties": {
         "sentiment": { "type": "string", "enum": ["positive", "negative", "mixed"] },
         "topics": { "type": "array", "items": { "type": "string" } }
       }
     }
     ```
3. **Run** and open the node's **output**. `result` holds JSON that matches the schema, such as
   `{"sentiment": "mixed", "topics": ["delivery", "packaging", "support"]}`. If the model's
   reply doesn't match, the node asks it again.
4. Add an If node: `{{ input.result.sentiment }}` `equals` `negative`. Because the output is
   validated, you can branch on it safely.

## 3. The CV inbox

1. Create the folder `Documents\CV Inbox`.
2. **Import** [`cv_inbox.json`](../../examples/cv_inbox.json) and **Save**. If you're using
   Ollama, click **analyze** and set **Provider** to `ollama` and **Model** to `llama3.2`,
   and set the credential on its **settings** tab to *none*.
3. Switch it to **Active**.
4. Save a CV as a `.txt` or `.md` file into `CV Inbox`. You can write a short made-up one.
5. A few seconds later, `<name>.analysis.json` appears next to it, with the candidate's name,
   seniority, years of experience, skills and a summary.

## Check your work

- The review classifier returns one of the three allowed sentiments every time.
- The `.analysis.json` file only contains facts from the CV, as the system prompt asks.

## Challenges

- Import [`job_pipeline.json`](../../examples/job_pipeline.json). It fetches real remote job
  posts, scores each one against a CV with the AI Agent, and emails you the best matches.
  Change `cv_text` in the trigger's sample data to your own CV. Leave `dry_run` on until you've
  set `recipient` and added a `gmail` credential ([lab 6](06-credentials-and-email.md)).
- Compare models: run the same review through Ollama and Anthropic and look at `usage` in each
  output.
- Lower **Temperature** to `0` for more consistent classifications.

## What you learned

- **Input Data** is how you hand the model data from earlier nodes. Keep instructions in
  **Prompt** and **System Prompt**.
- An **Output Schema** turns free text into reliable JSON you can route and store.
- Ollama runs entirely on your PC, so nothing leaves your machine.

**Next:** [Lab 9: Browser automation](09-browser-automation.md)
