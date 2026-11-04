from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from prospector import fx
from tests.web.conftest import TAILNET

T = fx.today()


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


@pytest.fixture
def money(ctx):
    ctx.fx.tnd_override = None
    ctx.conn.execute("INSERT INTO fx_rates VALUES (?,?,?,?)", (T.isoformat(), "TND", 3.0, "t"))
    fl = ctx.accounts.create("Freelancer balance", "USD")
    bank = ctx.accounts.create("BIAT", "TND")
    wid = ctx.works.create(title="Scraper bot", started_on=T)
    ctx.works.add_received(wid, 500_000, "USD", T, fl, ctx.fx)
    return fl, bank


@pytest.mark.parametrize("q", ["month=13-2026", "account=x", "month=&account=", "month=2026-00", "account=999", "month=abc"])
def test_money_tab_filters_lenient(client, money, q):
    r = client.get(f"/work/money?{q}")
    assert r.status_code == 200 and "Scraper bot" in r.text


def test_money_tab_lists_payments_and_transfers(client, ctx, money):
    fl, bank = money
    ctx.accounts.add_transfer(T, fl, bank, 300_000, 870_000)
    page = client.get("/work/money").text
    assert "Scraper bot" in page and "$500" in page
    assert "Freelancer balance → BIAT" in page and "870 TND" in page and "fee ≈ $10" in page
    only_bank = client.get(f"/work/money?account={bank}").text
    assert "Scraper bot" not in only_bank and "870 TND" in only_bank


def test_monthly_totals_current_year(client, ctx, money):
    fl, _ = money
    page = client.get("/work/money").text
    assert f'aria-label="Received per month in {T.year}' in page and "$500" in page


def test_record_transfer_form(client, ctx, money):
    fl, bank = money
    assert 'name="sent"' in client.get("/work/transfers").text
    r = client.post("/work/transfers", data={"on_day": "", "from_account": str(fl), "to_account": str(bank),
                                             "sent": "300", "received": "870", "note": ""}, follow_redirects=False)
    assert r.status_code == 303 and ctx.accounts.balances()[bank] == 870_000
    r = client.post("/work/transfers", data={"from_account": str(fl), "to_account": str(fl), "sent": "1",
                                             "received": "1"})
    assert r.status_code == 400 and "different" in r.text


def test_overview_shows_balances(client, ctx, money):
    fl, bank = money
    ctx.accounts.add_transfer(T - timedelta(days=1), fl, bank, 300_000, 870_000)
    page = client.get("/work").text
    assert "$200" in page and "870 TND" in page and "≈ $290" in page and 'href="/work/transfers"' in page
