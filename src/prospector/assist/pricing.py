"""Bid money, computed by Prospector from the model's hour estimate (the model never sets prices)."""
import math
from dataclasses import dataclass

from prospector.models import Pay
from prospector.profile.model import Pricing


@dataclass
class Quote:
    hours: float
    fair: int          # USD, hours x rate, fitted into a USD budget
    competitive: int   # USD, hours x floor
    delivery_days: int
    warning: str | None  # budget and work don't fit
    note: str | None     # budget we can't compare (other currency, salary)


def _round(x: float) -> int:
    return math.floor(x + 0.5)


def tnd(usd: float, rate: float) -> int:
    """TND equivalent, for display only."""
    return _round(usd * rate)


def quote(hours: float, pricing: Pricing, pay: Pay | None) -> Quote:
    fair, competitive = _round(hours * pricing.rate), _round(hours * pricing.floor)
    # 20 % buffer; integer maths so 5 h at 6 h/day is exactly one day.
    days = max(1, math.ceil(hours * 6 / (5 * pricing.hours_per_day)))
    warning = note = None
    if pay and (pay.min is not None or pay.max is not None):
        if pay.currency != "USD":
            note = f"Client budget is in {pay.currency or 'an unknown currency'} — compare yourself."
        elif pay.period in ("hour", "fixed", None):
            hourly = pay.period == "hour"
            unit = " USD/hour" if hourly else " USD"
            ours_fair, ours_comp = (pricing.rate, pricing.floor) if hourly else (fair, competitive)
            if pay.max is not None and ours_comp > pay.max:
                warning = (f"Even the competitive price is above the client's budget (max {pay.max:g}{unit}) — "
                           "skip it or bid high and explain.")
            elif pay.max is not None and ours_fair > pay.max:
                fair = _round(hours * pay.max) if hourly else _round(pay.max)
            elif pay.min is not None and ours_fair < pay.min:
                warning = f"Your fair price is below the client's minimum ({pay.min:g}{unit}) — you can bid higher."
        else:
            note = f"Client pay is per {pay.period} — compare yourself."
    return Quote(hours, fair, competitive, days, warning, note)
