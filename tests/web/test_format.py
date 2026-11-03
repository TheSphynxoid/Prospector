from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from prospector.models import Pay
from prospector.web.format import fmt_ago, fmt_pay, paragraphs
from tests.web.conftest import TAILNET

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


@pytest.mark.parametrize("pay, text", [
    (Pay(60000, 80000, "USD", "year"), "$60–80k / year"),
    (Pay(500, None, "EUR", "fixed"), "€500 fixed"),
    (Pay(2000, 2000, "TND", "month"), "TND 2,000 / month"),
    (Pay(None, 50, "GBP", "hour"), "up to £50 / hour"),
    (Pay(45000, 52500, "EUR", "year"), "€45,000–52,500 / year"),
    (Pay(25.5, 40, "USD", "hour"), "$25.5–40 / hour"),
    (Pay(1000, None, None, None), "1,000"),
    (None, "not stated"),
])
def test_fmt_pay(pay, text):
    assert fmt_pay(pay) == text


@pytest.mark.parametrize("delta, text", [
    (timedelta(seconds=30), "just now"), (timedelta(minutes=5), "5m ago"), (timedelta(hours=3), "3h ago"),
    (timedelta(days=2), "2d ago"), (timedelta(days=40), "24 Sep 2026"),
])
def test_fmt_ago(delta, text):
    assert fmt_ago(NOW - delta, NOW) == text
    assert fmt_ago((NOW - delta).isoformat(), NOW) == text


def test_fmt_ago_none_and_naive():
    assert fmt_ago(None, NOW) == ""
    assert fmt_ago(datetime(2026, 11, 3, 9), NOW) == "3h ago"  # naive = UTC


def test_paragraphs():
    body = "Intro line one\nstill intro\n\n- one\n- two\n\n• three\n* four\n\nOutro"
    assert paragraphs(body) == [("p", "Intro line one\nstill intro"), ("ul", ["one", "two"]),
                                ("ul", ["three", "four"]), ("p", "Outro")]
    assert paragraphs("") == []
    assert paragraphs("flat text with - a dash") == [("p", "flat text with - a dash")]


def test_detail_renders_list_and_pay(ctx, app, make_lead):
    client = TestClient(app, client=TAILNET)
    lid = ctx.leads.insert(make_lead(body="Intro\n\n- one\n- two", pay=Pay(60000, 80000, "USD", "year")))
    page = client.get(f"/lead/{lid}").text
    assert "<li>one</li>" in page and "<p>Intro</p>" in page and "$60–80k / year" in page


def test_row_shows_age(ctx, app, make_lead):
    client = TestClient(app, client=TAILNET)
    ctx.leads.insert(make_lead(posted_at=datetime.now(UTC) - timedelta(hours=3)))
    assert "posted 3h ago" in client.get("/leads").text
