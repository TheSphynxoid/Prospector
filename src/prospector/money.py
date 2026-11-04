"""Amounts are integer thousandths of a currency unit ("milli"), so TND millimes stay exact."""
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

_PREFIX = {"USD": "$", "EUR": "€", "GBP": "£"}


MAX_AMOUNT = Decimal(10) ** 9  # a billion of anything is a typo here
_SHAPE = re.compile(r"\d[\d.,]*")
_GROUPS = re.compile(r"\d{1,3}(?:[.,]\d{3})+")


def _normalise(s: str) -> str:
    """Digits with "." as the decimal point, from the ways people write amounts in English and French."""
    if "," in s and "." in s:  # both: whichever comes last is the decimal point
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        whole, frac = s.rsplit(dec, 1)
        if not _GROUPS.fullmatch(whole) and not whole.isdigit() or not frac.isdigit():
            raise ValueError("Enter an amount like 1200 or 1 200,50.")
        return whole.replace(",", "").replace(".", "") + "." + frac
    sep = "," if "," in s else "." if "." in s else None
    if sep is None:
        return s
    if s.count(sep) > 1:  # 1,200,000 or 1.200.000: thousands only
        if not _GROUPS.fullmatch(s):
            raise ValueError("Enter an amount like 1200 or 1 200,50.")
        return s.replace(sep, "")
    whole, frac = s.split(sep)
    if len(frac) == 3 and whole.lstrip("0"):
        raise ValueError(f"“{s}” could mean thousands or decimals: write 1200 or 1,20.")
    return f"{whole}.{frac}"


def parse_amount(text: str) -> int:
    """A positive amount typed by a person: "1200", "1 200,50", "1.200,50", "1,200.50", "12,5"."""
    s = "".join((text or "").replace(" ", " ").split())
    if not _SHAPE.fullmatch(s):
        raise ValueError("Enter an amount like 1200 or 1 200,50.")
    try:
        d = Decimal(_normalise(s))
    except InvalidOperation:
        raise ValueError("Enter an amount like 1200 or 1 200,50.") from None
    if d <= 0:
        raise ValueError("Enter an amount above zero.")
    if d > MAX_AMOUNT:
        raise ValueError("That amount is too large.")
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
