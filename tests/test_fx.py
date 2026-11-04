import math
from datetime import UTC, date, datetime

import httpx
import pytest
import respx

from prospector import fx
from prospector.fx import PRIMARY, SECONDARY, Rates, fetch_rates
from prospector.store.db import connect
from tests.test_scheduler import make_ctx

NOW = datetime(2026, 11, 4, 2, 30, tzinfo=UTC)
TODAY = date(2026, 11, 4)


def primary(**rates):
    return {"result": "success", "rates": {"USD": 1, **rates}}


def secondary(**rates):
    return {"date": "2026-11-04", "usd": {k.lower(): v for k, v in rates.items()}}


@pytest.fixture
def ctx(tmp_path):
    c = make_ctx(tmp_path)
    c.http = httpx.Client()
    return c


def stored(ctx):
    return {r["code"]: (r["per_usd"], r["source"]) for r in ctx.conn.execute("SELECT * FROM fx_rates")}


@respx.mock
def test_fetch_primary_stores_all_currencies(ctx):
    respx.get(PRIMARY).respond(json=primary(EUR=0.89, TND=3.004, GBP=0.78))
    fetch_rates(ctx, NOW)
    assert stored(ctx) == {"EUR": (0.89, "open.er-api.com"), "TND": (3.004, "open.er-api.com"),
                           "GBP": (0.78, "open.er-api.com")}
    assert ctx.health.get("fx").last_error is None and ctx.health.get("fx").last_count == 3


@respx.mock
def test_fetch_falls_back_to_second_source(ctx):
    respx.get(PRIMARY).respond(500)
    respx.get(SECONDARY).respond(json=secondary(EUR=0.894, TND=2.987, GBP=0.78))
    fetch_rates(ctx, NOW)
    assert stored(ctx)["TND"] == (2.987, "currency-api")


@respx.mock
@pytest.mark.parametrize("bad", [None, "x", 30.0, -1, float("nan")])
def test_fetch_rejects_missing_or_bad_values(ctx, bad):
    ctx.conn.execute("INSERT INTO fx_rates VALUES ('2026-11-01','TND',3.0,'seed')")
    tnd = {} if bad is None else {"TND": bad}
    if isinstance(bad, float) and math.isnan(bad):  # NaN is what Python's json would read from a sloppy server
        respx.get(PRIMARY).respond(content=b'{"result":"success","rates":{"EUR":0.89,"GBP":0.78,"TND":NaN}}')
    else:
        respx.get(PRIMARY).respond(json=primary(EUR=0.89, GBP=0.78, **tnd))
    respx.get(SECONDARY).respond(500)
    fetch_rates(ctx, NOW)
    rows = {r["code"]: r["day"] for r in ctx.conn.execute("SELECT * FROM fx_rates WHERE day = '2026-11-04'")}
    assert "TND" not in rows and {"EUR", "GBP"} <= set(rows)
    assert ctx.fx.rate("TND", TODAY) == 3.0  # last known


@respx.mock
def test_fetch_fills_gap_from_second_source(ctx):
    respx.get(PRIMARY).respond(json=primary(EUR=0.89, GBP=0.78))  # no TND
    respx.get(SECONDARY).respond(json=secondary(EUR=0.9, TND=2.99, GBP=0.79))
    fetch_rates(ctx, NOW)
    s = stored(ctx)
    assert s["TND"] == (2.99, "currency-api") and s["EUR"] == (0.89, "open.er-api.com")


@respx.mock
def test_fetch_both_fail_records_health_failure(ctx):
    respx.get(PRIMARY).mock(side_effect=httpx.ConnectError("down"))
    respx.get(SECONDARY).respond(json={"nope": 1})
    fetch_rates(ctx, NOW)
    assert ctx.health.get("fx").last_error and stored(ctx) == {}


def rates_with(**by_day):
    r = Rates(connect(":memory:"))
    for (code, day), v in by_day.items():
        r.conn.execute("INSERT INTO fx_rates VALUES (?,?,?,?)", (day, code, v, "t"))
    return r


def test_rate_nearest_earlier_then_later_then_builtin():
    r = Rates(connect(":memory:"))
    assert r.rate("TND", TODAY) == 3.0 and r.rate("EUR") == 0.92 and r.rate("GBP") == 0.79
    r.conn.execute("INSERT INTO fx_rates VALUES ('2026-11-10','TND',3.3,'t')")
    assert r.rate("TND", TODAY) == 3.3  # only a later one
    r.conn.execute("INSERT INTO fx_rates VALUES ('2026-11-01','TND',3.1,'t')")
    assert r.rate("TND", TODAY) == 3.1  # closest earlier wins
    assert r.rate("TND", date(2026, 11, 10)) == 3.3


def test_rate_usd_is_one_and_override_wins_for_tnd():
    r = Rates(connect(":memory:"), tnd_override=3.2)
    r.conn.execute("INSERT INTO fx_rates VALUES ('2026-11-04','EUR',0.9,'t')")
    assert r.rate("USD") == 1 and r.rate("TND") == 3.2 and r.rate("EUR", TODAY) == 0.9


def test_rate_unknown_code_raises():
    with pytest.raises(ValueError):
        Rates(connect(":memory:")).rate("JPY")


def test_convert_eur_to_tnd_via_usd():
    r = Rates(connect(":memory:"))
    r.conn.execute("INSERT INTO fx_rates VALUES ('2026-11-04','EUR',0.9,'t')")
    r.conn.execute("INSERT INTO fx_rates VALUES ('2026-11-04','TND',3.0,'t')")
    assert r.convert(100_000, "EUR", "TND", TODAY) == 333_333
    assert r.convert(100_000, "USD", "USD") == 100_000


def test_today_summary_and_stale():
    r = Rates(connect(":memory:"))
    assert r.today_summary() == (None, None, {}) and r.stale() and not r.has_today()
    d = fx.today().isoformat()
    for code, v in (("EUR", 0.9), ("TND", 3.0), ("GBP", 0.8)):
        r.conn.execute("INSERT INTO fx_rates VALUES (?,?,?,?)", (d, code, v, "open.er-api.com"))
    day, source, rates = r.today_summary()
    assert day == fx.today() and source == "open.er-api.com" and rates == {"EUR": 0.9, "TND": 3.0, "GBP": 0.8}
    assert not r.stale() and r.has_today()


def test_stale_when_newest_older_than_3_days():
    r = Rates(connect(":memory:"))
    old = date.fromordinal(fx.today().toordinal() - 4).isoformat()
    r.conn.execute("INSERT INTO fx_rates VALUES (?,?,?,?)", (old, "TND", 3.0, "t"))
    assert r.stale()


def test_today_is_tunis_date():
    assert fx.today(datetime(2026, 11, 3, 23, 30, tzinfo=UTC)) == date(2026, 11, 4)


def test_context_has_rates(ctx):
    assert isinstance(ctx.fx, Rates) and math.isclose(ctx.fx.rate("USD"), 1)
