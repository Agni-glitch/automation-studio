"""``{{ ... }}`` templating for node parameters.

Deliberately *not* Python ``eval``: an expression is a plain lookup path, so a workflow
file cannot execute code through its parameters. Supported forms::

    {{ input.title }}                      # output of the single upstream node
    {{ nodes.fetch_jobs.items[0].url }}    # output of any upstream node, by id
    {{ nodes["fetch-jobs"].items.0 }}      # quoted keys / numeric segments also work
    {{ trigger.path }}  {{ vars.recipient }}  {{ execution.id }}
    {{ input.body.name ?? "anonymous" }}   # fallback when missing/null (literal or another path)

A missing path is an error (it is usually a typo); use ``??`` to mark a value as optional.

If a string is exactly one expression, the raw value is substituted (keeping its type,
e.g. a dict or list). Otherwise each expression is stringified into the surrounding text.
Code-carrying parameters (e.g. a Python script) are excluded via ``BaseNode.raw_parameters``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Collection, Mapping
from typing import Any

from .errors import ExpressionError

_EXPR = re.compile(r"\{\{(.*?)\}\}", re.S)
_HEAD = re.compile(r"\s*([A-Za-z_][A-Za-z0-9_]*)")
_DOT = re.compile(r"\s*\.\s*([A-Za-z0-9_\-]+)")
_INDEX = re.compile(r"\s*\[\s*(-?\d+)\s*\]")
_KEY = re.compile(r"""\s*\[\s*(?:"([^"]*)"|'([^']*)')\s*\]""")

PathPart = str | int


def parse_path(expr: str) -> list[PathPart]:
    m = _HEAD.match(expr)
    if not m:
        raise ExpressionError(f"invalid expression '{{{{{expr}}}}}': must start with a name")
    parts: list[PathPart] = [m.group(1)]
    pos = m.end()
    end = len(expr.rstrip())
    while pos < end:
        if m := _DOT.match(expr, pos):
            parts.append(m.group(1))
        elif m := _INDEX.match(expr, pos):
            parts.append(int(m.group(1)))
        elif m := _KEY.match(expr, pos):
            parts.append(m.group(1) if m.group(1) is not None else m.group(2))
        else:
            raise ExpressionError(
                f"invalid expression '{{{{{expr}}}}}' near '{expr[pos:].strip()}'"
            )
        pos = m.end()
    return parts


def _format_path(parts: list[PathPart]) -> str:
    out = str(parts[0])
    for p in parts[1:]:
        out += f"[{p}]" if isinstance(p, int) else f".{p}"
    return out


def lookup(scope: Mapping[str, Any], expr: str) -> Any:
    parts = parse_path(expr)
    current: Any = scope
    for i, part in enumerate(parts):
        if isinstance(current, Mapping) and not isinstance(part, int) and part in current:
            current = current[part]
            continue
        if isinstance(current, (list, tuple)):
            idx = part if isinstance(part, int) else (int(part) if part.lstrip("-").isdigit() else None)
            if idx is not None and -len(current) <= idx < len(current):
                current = current[idx]
                continue
        where = _format_path(parts[: i + 1])
        hint = ""
        if i == 1 and parts[0] == "nodes":
            hint = " (only upstream nodes that produced output are visible)"
        raise ExpressionError(f"cannot resolve '{where}' in '{{{{{expr.strip()}}}}}'{hint}")
    return current


_LITERAL = re.compile(r'^\s*(?:"(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null|\[\s*\]|\{\s*\})\s*$')


def evaluate(scope: Mapping[str, Any], expr: str) -> Any:
    """Resolve ``path`` or a fallback chain ``path ?? other.path ?? "literal"``."""
    alternatives = expr.split("??")
    for i, alt in enumerate(alternatives):
        last = i == len(alternatives) - 1
        if _LITERAL.match(alt):
            return json.loads(alt)
        try:
            value = lookup(scope, alt)
        except ExpressionError:
            if last:
                raise
            continue
        if value is not None or last:
            return value
    return None  # unreachable


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def render(value: Any, scope: Mapping[str, Any]) -> Any:
    """Recursively resolve expressions inside strings, lists and dict values."""
    if isinstance(value, str):
        whole = _EXPR.fullmatch(value.strip())
        if whole and value.count("{{") == 1:
            return evaluate(scope, whole.group(1))
        return _EXPR.sub(lambda m: _stringify(evaluate(scope, m.group(1))), value)
    if isinstance(value, Mapping):
        return {k: render(v, scope) for k, v in value.items()}
    if isinstance(value, list):
        return [render(v, scope) for v in value]
    return value


def render_parameters(
    params: Mapping[str, Any], scope: Mapping[str, Any], raw: Collection[str] = ()
) -> dict[str, Any]:
    return {k: (v if k in raw else render(v, scope)) for k, v in params.items()}


def contains_expression(value: Any) -> bool:
    if isinstance(value, str):
        return bool(_EXPR.search(value))
    if isinstance(value, Mapping):
        return any(contains_expression(v) for v in value.values())
    if isinstance(value, list):
        return any(contains_expression(v) for v in value)
    return False
