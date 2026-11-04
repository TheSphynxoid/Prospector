"""Exchange rates: fetched once a day from free sources, stored per day, looked up without ever failing."""
import math
import sqlite3
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

import httpx

from prospector.http import describe_error
from prospector.store.stats import TZ

if TYPE_CHECKING:
    from prospector.context import AppContext

CURRENCIES: tuple[str, ...] = ("USD", "EUR", "TND", "GBP")
PRIMARY = "https://open.er-api.com/v6/latest/USD"
SECONDARY = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/usd.json"
BUILTIN = {"TND": 3.0, "EUR": 0.92, "GBP": 0.79}
MAX_JUMP = 0.20
STALE_DAYS = 3


def today(now: datetime | None = None) -> date:
    """The Africa/Tunis date (the owner's day), never the UTC one."""
    return (now or datetime.now(TZ)).astimezone(TZ).date()


class Rates:
    """Units of each currency per 1 USD."""

    def __init__(self, conn: sqlite3.Connection, tnd_override: float | None = None):
        self.conn = conn
        self.tnd_override = tnd_override

    def rate(self, code: str, day: date | None = None) -> float:
        if code not in CURRENCIES:
            raise ValueError(f"unsupported currency {code!r}")
        if code == "USD":
            return 1.0
        if code == "TND" and self.tnd_override:
            return float(self.tnd_override)
        d = (day or today()).isoformat()
        r = (self.conn.execute("SELECT per_usd FROM fx_rates WHERE code = ? AND day <= ? ORDER BY day DESC LIMIT 1",
                               (code, d)).fetchone()
             or self.conn.execute("SELECT per_usd FROM fx_rates WHERE code = ? AND day > ? ORDER BY day LIMIT 1",
                                  (code, d)).fetchone())
        return r["per_usd"] if r else BUILTIN[code]

    def convert(self, milli: int, src: str, dst: str, day: date | None = None) -> int:
        if src == dst:
            return milli
        value = Decimal(milli) * Decimal(repr(self.rate(dst, day))) / Decimal(repr(self.rate(src, day)))
        return int(value.quantize(Decimal(1), ROUND_HALF_UP))

    def latest(self, code: str) -> float | None:
        r = self.conn.execute("SELECT per_usd FROM fx_rates WHERE code = ? ORDER BY day DESC LIMIT 1", (code,)).fetchone()
        return r["per_usd"] if r else None

    def today_summary(self) -> tuple[date | None, str | None, dict[str, float]]:
        """The newest stored day, its source(s), and its rates."""
        r = self.conn.execute("SELECT MAX(day) AS d FROM fx_rates").fetchone()
        if not r or r["d"] is None:
            return None, None, {}
        rows = self.conn.execute("SELECT code, per_usd, source FROM fx_rates WHERE day = ?", (r["d"],)).fetchall()
        return (date.fromisoformat(r["d"]), ", ".join(sorted({x["source"] for x in rows})),
                {x["code"]: x["per_usd"] for x in rows})

    def has_today(self) -> bool:
        return self.today_summary()[0] == today()

    def stale(self) -> bool:
        day = self.today_summary()[0]
        return day is None or day < today() - timedelta(days=STALE_DAYS)


def _plausible(value, previous: float | None) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value) or value <= 0:
        return False
    return previous is None or abs(value - previous) <= MAX_JUMP * previous


def _from_primary(data: dict) -> dict:
    return data.get("rates", {}) if data.get("result") == "success" else {}


def _from_secondary(data: dict) -> dict:
    return {k.upper(): v for k, v in (data.get("usd") or {}).items()}


def fetch_rates(ctx: "AppContext", now: datetime) -> None:
    """Store today's rates. A code one source lacks or gets wrong comes from the next source, else is skipped
    (the last known rate keeps being used)."""
    rates: Rates = ctx.fx
    wanted = [c for c in CURRENCIES if c != "USD"]
    got: dict[str, tuple[float, str]] = {}
    errors = []
    for url, name, pick in ((PRIMARY, "open.er-api.com", _from_primary), (SECONDARY, "currency-api", _from_secondary)):
        if len(got) == len(wanted):
            break
        try:
            resp = ctx.http.get(url, timeout=20)
            resp.raise_for_status()
            values = pick(resp.json())
        except httpx.HTTPError as e:
            errors.append(f"{name}: {describe_error(e)}")
            continue
        except ValueError:
            errors.append(f"{name}: not JSON")
            continue
        for code in wanted:
            if code not in got and _plausible(values.get(code), rates.latest(code)):
                got[code] = (float(values[code]), name)
    day = today(now).isoformat()
    for code, (value, source) in got.items():
        ctx.conn.execute("INSERT OR REPLACE INTO fx_rates(day, code, per_usd, source) VALUES (?,?,?,?)",
                         (day, code, value, source))
    if got:
        ctx.health.record_success("fx", len(got), drift=False)
    else:
        ctx.health.record_failure("fx", "; ".join(errors) or "no usable rates in either source")
