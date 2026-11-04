from datetime import date

import pytest

from prospector import fx

D = date(2026, 11, 4)


def rate(ctx, code, v, day=D):
    ctx.conn.execute("INSERT OR REPLACE INTO fx_rates VALUES (?,?,?,?)", (day.isoformat(), code, v, "t"))


def work(ctx, **kw):
    return ctx.works.create(**(dict(title="Scraper bot", client="Direct", kind="gig", price_milli=500_000,
                                    currency="USD", started_on=D) | kw))


def test_create_and_stage_update(wctx):
    wid = work(wctx)
    w = wctx.works.get(wid)
    assert (w.stage, w.price_milli, w.started_on, w.ended_on) == ("in_progress", 500_000, D, None)
    wctx.works.update(wid, stage="closed", ended_on=D)
    assert wctx.works.get(wid).ended_on == D
    assert [x.id for x in wctx.works.list(stage="closed")] == [wid]


def test_receive_freezes_rates(wctx):
    rate(wctx, "EUR", 0.9)
    acc = wctx.accounts.create("Payoneer", "USD")
    wid = work(wctx)
    pid = wctx.works.add_expected(wid, 90_000, "EUR", date(2026, 11, 20))
    assert wctx.works.payments(wid)[0].status == "expected" and wctx.works.paid_usd_milli(wid) == 0
    wctx.works.receive(pid, D, acc, wctx.fx)
    p = wctx.works.payments(wid)[0]
    assert (p.status, p.received_on, p.usd_rate, p.usd_milli, p.account_milli) == ("received", D, 0.9, 100_000, 100_000)
    rate(wctx, "EUR", 0.5)
    assert wctx.works.payments(wid)[0].usd_milli == 100_000  # frozen
    assert wctx.works.paid_usd_milli(wid) == 100_000


def test_receive_into_other_currency_account(wctx):
    rate(wctx, "TND", 3.0)
    bank = wctx.accounts.create("BIAT", "TND")
    wid = work(wctx)
    wctx.works.add_received(wid, 100_000, "USD", D, bank, wctx.fx)
    assert wctx.works.payments(wid)[0].account_milli == 300_000
    assert wctx.accounts.received_totals() == {bank: 300_000}


def test_paid_usd_counts_received_only_and_periods(wctx):
    acc = wctx.accounts.create("Freelancer balance", "USD")
    wid = work(wctx)
    wctx.works.add_received(wid, 200_000, "USD", D, acc, wctx.fx)
    wctx.works.add_received(wid, 50_000, "USD", date(2026, 10, 1), acc, wctx.fx)
    wctx.works.add_expected(wid, 300_000, "USD", None)
    assert wctx.works.paid_usd_milli(wid) == 250_000
    assert [p.amount_milli for p in wctx.works.received_between(date(2026, 11, 1), date(2026, 11, 30))] == [200_000]
    assert [p.amount_milli for p in wctx.works.expected()] == [300_000]


def test_delete_payment_and_cascade(wctx):
    wid = work(wctx)
    pid = wctx.works.add_expected(wid, 1000, "USD", None)
    wctx.works.delete_payment(pid)
    assert wctx.works.payments(wid) == []


def test_unsupported_currency_rejected(wctx):
    with pytest.raises(ValueError):
        wctx.works.add_expected(work(wctx), 1000, "JPY", None)
    assert fx
