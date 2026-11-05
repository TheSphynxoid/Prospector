"""Bid money, computed by Prospector from the model's hour estimate (the model never sets prices)."""
import math
from dataclasses import dataclass

from prospector.models import Pay
from prospector.profile.model import Pricing


@dataclass
class Quote:
    hours: float
    fair: int          # hours x rate, fitted into the budget, in `currency`
    competitive: int   # hours x floor, in `currency`
    delivery_days: int
    warning: str | None  # budget and work don't fit
    note: str | None     # budget we can't compare (other currency, salary)
    currency: str = "USD"


def _round(x: float) -> int:
    return math.floor(x + 0.5)


def tnd(amount: float, rate: float) -> int:
    """TND equivalent, for display only (rate: TND per unit of the amount's currency)."""
    return _round(amount * rate)


def bid_currency(pay: Pay | None) -> str:
    """The posting's currency when we have rates for it, else USD."""
    from prospector.fx import CURRENCIES

    return pay.currency if pay and pay.currency in CURRENCIES else "USD"


def in_currency(pricing: Pricing, per_usd: float) -> Pricing:
    """The owner's USD rate and floor, expressed in another currency."""
    return pricing.model_copy(update={"rate": pricing.rate * per_usd, "floor": pricing.floor * per_usd})


def quote(hours: float, pricing: Pricing, pay: Pay | None, currency: str = "USD") -> Quote:
    fair, competitive = _round(hours * pricing.rate), _round(hours * pricing.floor)
    # 20 % buffer; integer maths so 5 h at 6 h/day is exactly one day.
    days = max(1, math.ceil(hours * 6 / (5 * pricing.hours_per_day)))
    warning = note = None
    if pay and (pay.min is not None or pay.max is not None):
        if pay.currency != currency:
            note = f"Client budget is in {pay.currency or 'an unknown currency'} — compare yourself."
        elif pay.period in ("hour", "fixed", None):
            hourly = pay.period == "hour"
            unit = f" {currency}/hour" if hourly else f" {currency}"
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
    return Quote(hours, fair, competitive, days, warning, note, currency)

