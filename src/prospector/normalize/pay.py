import re

from prospector.models import Pay, PayPeriod

_CURRENCIES = [  # order matters: AUD/CAD before plain "$"
    ("AUD", r"\baud\b|a\$"),
    ("CAD", r"\bcad\b|c\$"),
    ("EUR", r"€|\beur\b|\beuros?\b"),
    ("GBP", r"£|\bgbp\b"),
    ("TND", r"\btnd\b|\bdt\b|\bdinars?\b"),
    ("USD", r"\$|\busd\b"),
]
_PERIODS: list[tuple[PayPeriod, str]] = [
    ("hour", r"\b(hr|hour|hourly|heure)s?\b|/h\b"),
    ("day", r"\b(day|daily|jour)s?\b"),
    ("month", r"\b(mo|month|monthly|mois)\b"),
    ("year", r"\b(yr|year|yearly|annual|annum|an|ans)\b|/a\b"),
]
# "1 500", "120,000", "50.000" (thousands groups) or a plain/decimal number, optional k suffix
_NUMBER = re.compile(r"(\d{1,3}(?:[   ,.]\d{3})+|\d+(?:\.\d+)?)\s*(k)?(?![a-z])")
_UP_TO = re.compile(r"\b(up to|jusqu'?à|max(imum)?)\b")


def _to_float(num: str, k: str | None) -> float:
    if re.fullmatch(r"\d{1,3}(?:[   ,.]\d{3})+", num):
        num = re.sub(r"[   ,.]", "", num)
    value = float(num)
    return value * 1000 if k else value


def parse_pay(text: str | None) -> Pay | None:
    """Best-effort pay parse. Returns None when no currency + amount is found; never raises."""
    if not text:
        return None
    t = text.lower().replace("–", "-").replace("—", "-")
    currency = next((code for code, pat in _CURRENCIES if re.search(pat, t)), None)
    if currency is None:
        return None
    values = [_to_float(n, k) for n, k in _NUMBER.findall(t)]
    if not values:
        return None
    period = next((p for p, pat in _PERIODS if re.search(pat, t)), None)
    if len(values) == 1:
        if _UP_TO.search(t):
            return Pay(None, values[0], currency, period)
        return Pay(values[0], values[0], currency, period)
    low, high = sorted(values[:2])
    return Pay(low, high, currency, period)
