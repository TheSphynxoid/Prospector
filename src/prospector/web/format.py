"""Display helpers registered as Jinja filters."""
import re
from datetime import UTC, datetime
from typing import Literal

from prospector.models import Pay

_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£"}
_BULLET = re.compile(r"^\s*[-*•]\s+")


def _amount(n: float) -> str:
    return f"{n:,.0f}" if float(n).is_integer() else f"{n:,.2f}".rstrip("0").rstrip(".")


def fmt_pay(p: Pay | None) -> str:
    if p is None or (p.min is None and p.max is None):
        return "not stated"
    lo, hi = p.min, p.max
    if lo is not None and hi is not None and lo != hi:
        if lo >= 1000 and hi >= 1000 and lo % 1000 == 0 and hi % 1000 == 0:
            amount = f"{_amount(lo / 1000)}–{_amount(hi / 1000)}k"
        else:
            amount = f"{_amount(lo)}–{_amount(hi)}"
    elif lo is not None:
        amount = _amount(lo)
    else:
        amount = None
    cur = p.currency or ""
    sym = _SYMBOLS.get(cur)

    def money(a: str) -> str:
        return f"{sym}{a}" if sym else (f"{cur} {a}" if cur else a)

    text = money(amount) if amount is not None else f"up to {money(_amount(hi))}"
    if p.period == "fixed":
        return f"{text} fixed"
    return f"{text} / {p.period}" if p.period else text


def fmt_ago(ts: datetime | str | None, now: datetime) -> str:
    if not ts:
        return ""
    dt = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    secs = (now - dt).total_seconds()
    if secs < 60:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    if secs < 30 * 86400:
        return f"{int(secs // 86400)}d ago"
    return dt.strftime("%d %b %Y")


def paragraphs(body: str) -> list[tuple[Literal["p", "ul"], str | list[str]]]:
    """Blank-line separated blocks; a block made only of bullet lines becomes a list."""
    out: list = []
    for block in re.split(r"\n\s*\n", body or ""):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        if not lines:
            continue
        if all(_BULLET.match(ln) for ln in lines):
            out.append(("ul", [_BULLET.sub("", ln).strip() for ln in lines]))
        else:
            out.append(("p", "\n".join(ln.strip() for ln in lines)))
    return out
