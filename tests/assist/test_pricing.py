import pytest

from prospector.assist.pricing import quote, tnd
from prospector.models import Pay
from prospector.profile.model import Pricing

P = Pricing(rate=25, floor=15, hours_per_day=6)


def test_no_pay():
    q = quote(10, P, None)
    assert (q.fair, q.competitive, q.delivery_days, q.warning, q.note) == (250, 150, 2, None, None)


def test_usd_budget_clamps_fair_to_max():
    q = quote(10, P, Pay(100, 200, "USD", "fixed"))
    assert (q.fair, q.competitive, q.warning) == (200, 150, None)


def test_fair_below_client_minimum_warns():
    q = quote(10, P, Pay(300, 500, "USD", "fixed"))
    assert q.fair == 250
    assert q.warning == "Your fair price is below the client's minimum (300 USD) — you can bid higher."


def test_competitive_above_max_warns():
    q = quote(20, P, Pay(50, 100, "USD", "fixed"))
    assert (q.fair, q.competitive) == (500, 300)
    assert q.warning == ("Even the competitive price is above the client's budget (max 100 USD) — "
                         "skip it or bid high and explain.")


def test_other_currency_not_converted():
    q = quote(10, P, Pay(100, 200, "EUR", "fixed"))
    assert (q.fair, q.warning, q.note) == (250, None, "Client budget is in EUR — compare yourself.")


def test_hourly_budget_compares_rates():
    q = quote(10, P, Pay(10, 20, "USD", "hour"))
    assert (q.fair, q.competitive, q.warning) == (200, 150, None)
    q = quote(10, P, Pay(5, 12, "USD", "hour"))
    assert q.warning == ("Even the competitive price is above the client's budget (max 12 USD/hour) — "
                         "skip it or bid high and explain.")
    q = quote(10, P, Pay(40, 60, "USD", "hour"))
    assert q.warning == "Your fair price is below the client's minimum (40 USD/hour) — you can bid higher."


def test_salary_periods_not_compared():
    q = quote(10, P, Pay(3000, 4000, "USD", "month"))
    assert (q.fair, q.warning, q.note) == (250, None, "Client pay is per month — compare yourself.")


def test_budget_with_only_max():
    assert quote(10, P, Pay(None, 200, "USD", "fixed")).fair == 200


@pytest.mark.parametrize("hours, days", [(0.5, 1), (5, 1), (6, 2), (10, 2), (30, 6)])
def test_delivery_days(hours, days):
    assert quote(hours, P, None).delivery_days == days


def test_rounds_half_up_and_tnd():
    q = quote(0.5, P, None)
    assert (q.fair, q.competitive) == (13, 8)
    assert tnd(250, 3.0) == 750 and tnd(10, 3.15) == 32


def _rates(**codes):
    from prospector import fx
    from prospector.fx import Rates
    from prospector.store.db import connect
    r = Rates(connect(":memory:"))
    for code, v in codes.items():
        r.conn.execute("INSERT INTO fx_rates VALUES (?,?,?,?)", (fx.today().isoformat(), code, v, "t"))
    return r


def test_bid_currency_follows_supported_pay():
    from prospector.assist.pricing import bid_currency
    assert bid_currency(Pay(1, 2, "EUR", "fixed")) == "EUR"
    assert bid_currency(Pay(1, 2, "TND", "month")) == "TND"
    for pay in (Pay(1, 2, "JPY", "fixed"), Pay(1, 2, None, "fixed"), None):
        assert bid_currency(pay) == "USD"


def test_pricing_in_currency_scales_rate_and_floor():
    from prospector.assist.pricing import in_currency
    p = in_currency(P, 0.9)
    assert (p.rate, p.floor, p.hours_per_day) == (22.5, 13.5, 6)


def test_quote_in_eur_compares_eur_budget():
    from prospector.assist.pricing import in_currency
    q = quote(10, in_currency(P, 0.9), Pay(100, 180, "EUR", "fixed"), "EUR")
    assert (q.fair, q.competitive, q.currency, q.note) == (180, 135, "EUR", None)
    q = quote(10, in_currency(P, 0.9), Pay(5, 10, "EUR", "hour"), "EUR")
    assert q.warning == ("Even the competitive price is above the client's budget (max 10 EUR/hour) — "
                         "skip it or bid high and explain.")
