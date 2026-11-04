# Contributing to Automation Studio

Thanks for helping. Bug reports, fixes, new nodes, docs and example workflows are all welcome.

- **Found a bug?** [Open a bug report](https://github.com/Agni-glitch/automation-studio/issues/new?template=bug_report.yml).
- **Have an idea?** [Open a feature request](https://github.com/Agni-glitch/automation-studio/issues/new?template=feature_request.yml) before writing a large change, so we can agree on the approach first.
- **Found a security problem?** Don't open an issue. Follow [SECURITY.md](SECURITY.md).

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## Set up a development copy

You need Windows 10 or 11, Python 3.11 or newer, Node.js 20 or newer, and Git.

```powershell
git clone https://github.com/Agni-glitch/automation-studio.git
cd automation-studio
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,browser,desktop,build]"
cd frontend; npm ci; npm run build; cd ..
python -m pytest -q
```

Run the app from source:

```powershell
python main.py open                  # desktop window; starts the background service
python main.py serve --dev           # service that accepts the Vite dev server, in one terminal
cd frontend; npm run dev             # editor at http://localhost:5173, in another
```

The engine, triggers and CLI also work on their own without the frontend. See
[docs/architecture.md](docs/architecture.md) for how the pieces fit together.

## Make a change

1. Fork the repository and create a branch from `main` (`fix-webhook-timeout`, `node-slack`).
2. Keep each pull request to one change. Small pull requests get reviewed faster.
3. Add or update tests in `tests/` for anything that changes behavior.
4. Run the checks below before pushing.
5. Open a pull request and fill in the template. CI must pass before it can be merged.

`main` is protected: every change goes through a pull request with passing CI, and history
stays linear (squash or rebase merges).

### Checks

```powershell
python -m pytest -q                  # backend, engine, triggers, updater
cd frontend; npm run typecheck       # TypeScript
```

If you changed packaging (`build/`), also run `python build/package.py --skip-frontend` and
start the built `build\output\dist\AutomationStudio\AutomationStudio.exe`.

## Code style

- **Python:** type hints on public functions, `from __future__ import annotations`, Pydantic
  models for anything that crosses a boundary (node parameters, API bodies). Lines up to about
  110 characters. Prefer clear names over comments; comment the *why* when it isn't obvious.
- **TypeScript/React:** function components and hooks; API types live in `frontend/src/types.ts`.
- **Security:** never log secrets (credentials are redacted by the engine; keep it that way),
  keep the API bound to `127.0.0.1`, and don't evaluate user strings as code outside the Python
  sandbox.
- **Commits:** a short imperative summary line ("Add Slack node", "Fix cron DST skip"), and a
  body when the reason isn't obvious.

## Adding a node

Nodes are the most common contribution. A node is a class in `engine/nodes/` registered with
`@register_node`. Its parameter form in the editor is generated from the Pydantic `Parameters`
model, so no frontend work is needed for most nodes.

```python
from pydantic import BaseModel, Field
from engine import BaseNode, NodeContext, register_node

@register_node
class UppercaseNode(BaseNode):
    type = "logic.uppercase"          # category.name, unique
    display_name = "Uppercase"
    category = "logic"

    class Parameters(BaseModel):
        text: str = Field(description="Text to convert")

    async def execute(self, ctx: NodeContext, params: Parameters):
        ctx.info(f"uppercasing {len(params.text)} chars")
        return {"text": params.text.upper()}
```

- Import the module in `engine/nodes/__init__.py`.
- Raise `NonRetryableError` for failures a retry can't fix (bad input, 4xx); other exceptions
  are retried according to the node's retry policy.
- Use `ctx.run_blocking(...)` for blocking libraries so the event loop keeps running.
- Read secrets with `await ctx.get_credential("default")` (the slot named in the node's
  `credentials`); never put them in parameters.
- Add tests to `tests/test_nodes.py`, using `httpx.MockTransport` instead of real network calls.

## Releases

Maintainers publish releases with `python build/release.py` (see
[docs/building.md](docs/building.md)). Contributors don't need to bump the version.

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
