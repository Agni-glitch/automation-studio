"""Standard 5-field cron expressions, evaluated in local time.

    ┌ minute (0-59)   ┌ hour (0-23)   ┌ day of month (1-31)   ┌ month (1-12 or JAN-DEC)   ┌ day of week (0-6 or SUN-SAT, 7 = SUN)
    */15              9-17            *                       *                           MON-FRI

Supports ``*``, ``a``, ``a-b``, ``*/n``, ``a-b/n``, ``a/n``, comma lists, names, and the
macros @hourly @daily @weekly @monthly @yearly. As in classic cron, when both day-of-month
and day-of-week are restricted, a day matches if EITHER matches.
"""

from __future__ import annotations

from datetime import datetime, timedelta

MACROS = {
    "@yearly": "0 0 1 1 *",
    "@annually": "0 0 1 1 *",
    "@monthly": "0 0 1 * *",
    "@weekly": "0 0 * * 0",
    "@daily": "0 0 * * *",
    "@midnight": "0 0 * * *",
    "@hourly": "0 * * * *",
}
_MONTHS = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}
_DAYS = {d: i for i, d in enumerate(["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"])}
_SEARCH_LIMIT = timedelta(days=366 * 5)


def _parse_field(text: str, low: int, high: int, names: dict[str, int] | None = None) -> set[int]:
    def value(token: str) -> int:
        token = token.upper()
        if names and token in names:
            return names[token]
        if not token.isdigit():
            raise ValueError(f"invalid value '{token}'")
        return int(token)

    result: set[int] = set()
    for part in text.split(","):
        if not part:
            raise ValueError(f"empty list item in '{text}'")
        base, _, step_text = part.partition("/")
        step = int(step_text) if step_text else 1
        if step_text and (not step_text.isdigit() or step < 1):
            raise ValueError(f"invalid step in '{part}'")
        if base == "*":
            start, end = low, high
        elif "-" in base:
            a, b = base.split("-", 1)
            start, end = value(a), value(b)
        else:
            start = value(base)
            end = high if step_text else start
        if not (low <= start <= high and low <= end <= high) or start > end:
            raise ValueError(f"'{part}' is outside {low}-{high}")
        result.update(range(start, end + 1, step))
    return result


class CronExpression:
    def __init__(self, expression: str) -> None:
        self.expression = expression.strip()
        text = MACROS.get(self.expression.lower(), self.expression)
        fields = text.split()
        if len(fields) != 5:
            raise ValueError(f"cron expression needs 5 fields, got {len(fields)}: '{expression}'")
        minute, hour, dom, month, dow = fields
        try:
            self.minutes = _parse_field(minute, 0, 59)
            self.hours = _parse_field(hour, 0, 23)
            self.days = _parse_field(dom, 1, 31)
            self.months = _parse_field(month, 1, 12, _MONTHS)
            weekdays = _parse_field(dow, 0, 7, _DAYS)
        except ValueError as exc:
            raise ValueError(f"invalid cron expression '{expression}': {exc}") from None
        self.weekdays = {0 if d == 7 else d for d in weekdays}
        self._dom_any = dom == "*"
        self._dow_any = dow == "*"

    def _day_matches(self, dt: datetime) -> bool:
        dom_ok = dt.day in self.days
        dow_ok = (dt.weekday() + 1) % 7 in self.weekdays  # Python Monday=0 -> cron Sunday=0
        if self._dom_any or self._dow_any:
            return dom_ok and dow_ok
        return dom_ok or dow_ok

    def matches(self, dt: datetime) -> bool:
        return (dt.month in self.months and self._day_matches(dt)
                and dt.hour in self.hours and dt.minute in self.minutes)

    def next_after(self, dt: datetime) -> datetime:
        """First matching minute strictly after ``dt``."""
        t = dt.replace(second=0, microsecond=0) + timedelta(minutes=1)
        limit = t + _SEARCH_LIMIT
        while t < limit:
            if t.month not in self.months:
                t = (t.replace(day=1, hour=0, minute=0) + timedelta(days=32)).replace(day=1)
            elif not self._day_matches(t):
                t = t.replace(hour=0, minute=0) + timedelta(days=1)
            elif t.hour not in self.hours:
                t = t.replace(minute=0) + timedelta(hours=1)
            elif t.minute not in self.minutes:
                t += timedelta(minutes=1)
            else:
                return t
        raise ValueError(f"cron expression '{self.expression}' never fires")

    def __repr__(self) -> str:
        return f"CronExpression({self.expression!r})"
