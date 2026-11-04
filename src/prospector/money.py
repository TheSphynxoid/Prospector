"""Amounts are integer thousandths of a currency unit ("milli"), so TND millimes stay exact."""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_PREFIX = {"USD": "$", "EUR": "€", "GBP": "£"}


def parse_amount(text: str) -> int:
    """A positive amount typed by a person: "1200", "1 200,50", "1,200.50" (a lone comma is the decimal point)."""
    s = "".join((text or "").split())
    if "," in s and "." in s:
        s = s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        d = Decimal(s)
    except InvalidOperation:
        raise ValueError("Enter an amount like 1200 or 1 200,50.") from None
    if not d.is_finite() or d <= 0:
        raise ValueError("Enter an amount above zero.")
    milli = int((d * 1000).quantize(Decimal(1), ROUND_HALF_UP))
    if milli <= 0:
        raise ValueError("Enter an amount above zero.")
    return milli


def to_milli(x: float) -> int:
    return int(Decimal(repr(x)).scaleb(3).quantize(Decimal(1), ROUND_HALF_UP))


def from_milli(m: int) -> float:
    return m / 1000


def fmt(milli: int, code: str) -> str:
    sign, m = ("-" if milli < 0 else ""), abs(milli)
    if m % 1000 == 0:
        num = f"{m // 1000:,}"
    elif code == "TND" and m % 10:
        num = f"{m / 1000:,.3f}"
    else:
        num = f"{m / 1000:,.2f}"
    return f"{sign}{_PREFIX[code]}{num}" if code in _PREFIX else f"{sign}{num} {code}"
