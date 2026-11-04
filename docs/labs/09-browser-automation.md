# Lab 9: Browser automation

**You'll build:** a workflow that opens Hacker News in Microsoft Edge, collects the front-page
headlines and takes a screenshot.
**You'll learn:** browser steps, CSS selectors, extracting text and attributes, screenshots,
headless mode and saved logins.
**Needs:** Microsoft Edge (installed with Windows) and an internet connection. **Time:** 20 minutes.

The finished version is [`hn_headlines.json`](../../examples/hn_headlines.json).

## Steps

1. **Import** [`hn_headlines.json`](../../examples/hn_headlines.json) and **Save**.
2. Click **browse** and set **Headless** to off, so you can watch the browser.
3. Press **Run**. Edge opens, loads the page, and closes again.
4. Open **browse**'s **output**:
   - `data.titles`: every headline on the page
   - `data.top_link`: the first headline's link
   - `screenshots`: the path of the screenshot it took. Open it.
5. Open **top10**'s output and log: the first ten headlines, numbered.

## Find your own selectors

Every step that reads or clicks something needs a **selector** that finds it on the page.

1. Open the page in Edge, right-click the thing you want, and choose **Inspect**.
2. Look at the highlighted HTML. Here a headline is an `<a>` inside `<span class="titleline">`,
   so the selector is `.titleline > a`.
3. Test it in the DevTools **Console** before using it:
   `document.querySelectorAll(".titleline > a").length` should be about 30.

## Fill in a form

Make a second workflow that types into a search box and reads the result. Give its Manual
Trigger the sample data `{"query": "Home automation"}`, and give its Browser Automation node
these steps:

```json
[
  { "action": "goto", "url": "https://www.wikipedia.org", "timeout_ms": 45000 },
  { "action": "fill", "selector": "#searchInput", "value": "{{ input.query }}" },
  { "action": "press", "selector": "#searchInput", "value": "Enter" },
  { "action": "wait_for", "selector": "#firstHeading" },
  { "action": "extract_text", "selector": "#firstHeading", "name": "title" },
  { "action": "extract_text", "selector": "#mw-content-text p:not(.mw-empty-elt)", "name": "first_paragraph" },
  { "action": "screenshot" }
]
```

Run it, then change `query` and run again. `data.title` and `data.first_paragraph` hold the
article's title and opening paragraph.

If a selector stops matching (sites change their HTML), find the new one with **Inspect** as
above.

## Check your work

- `data.titles` has about 30 entries, and the screenshot shows the page.
- With **Headless** off you can see each step happen.

## Challenges

- **Stay logged in:** set **Profile Dir** to the full path of an empty folder, such as
  `C:\Users\<you>\Documents\studio-browser`. Run once with **Headless** off, log in to a site
  by hand during a long `wait` step, and later runs reuse that login.
- Use `evaluate` to run JavaScript on the page, for example
  `{"action": "evaluate", "value": "document.querySelectorAll('a').length", "name": "links"}`.
- Schedule it every morning and email yourself the top five (you'll do exactly this in the
  [capstone](12-capstone-daily-digest.md)).

## What you learned

- Browser steps run in order: `goto`, `fill`, `click`, `press`, `wait_for`, then `extract_*`
  steps store results in `data` under `name`.
- Each step has `timeout_ms` (15 seconds by default). Raise it for slow pages or networks.
- Respect each site's terms of use, and prefer an official API when there is one.

**Next:** [Lab 10: Desktop automation](10-desktop-automation.md)
