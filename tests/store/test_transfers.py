from datetime import date

import pytest

from prospector.store.accounts import transfer_cost

D = date(2026, 11, 4)


def setup(ctx):
    ctx.fx.tnd_override = None
    ctx.conn.execute("INSERT INTO fx_rates VALUES (?,?,?,?)", (D.isoformat(), "TND", 3.0, "t"))
    fl = ctx.accounts.create("Freelancer balance", "USD")
    bank = ctx.accounts.create("BIAT", "TND")
    wid = ctx.works.create(title="t", started_on=D)
    ctx.works.add_received(wid, 500_000, "USD", D, fl, ctx.fx)
    return fl, bank


def test_balance_receipts_plus_transfers(wctx):
    fl, bank = setup(wctx)
    tid = wctx.accounts.add_transfer(D, fl, bank, 300_000, 870_000, "withdrawal")
    assert wctx.accounts.balances() == {fl: 200_000, bank: 870_000}
    t = wctx.accounts.transfers()[0]
    assert (t.id, t.on_day, t.from_account, t.to_account, t.note) == (tid, D, fl, bank, "withdrawal")


def test_transfer_cost(wctx):
    fl, bank = setup(wctx)
    wctx.accounts.add_transfer(D, fl, bank, 300_000, 870_000)
    rate, fee = transfer_cost(wctx.accounts.transfers()[0], {a.id: a for a in wctx.accounts.list()}, wctx.fx)
    assert rate == pytest.approx(2.9) and fee == 10_000


def test_transfer_cost_never_negative(wctx):
    fl, bank = setup(wctx)
    wctx.accounts.add_transfer(D, fl, bank, 100_000, 310_000)  # better than market
    assert transfer_cost(wctx.accounts.transfers()[0], {a.id: a for a in wctx.accounts.list()}, wctx.fx)[1] == 0


def test_transfer_validation(wctx):
    fl, bank = setup(wctx)
    for args in ((fl, fl, 1000, 1000), (fl, bank, 0, 1000), (fl, bank, 1000, -1), (fl, 999, 1000, 1000)):
        with pytest.raises(ValueError):
            wctx.accounts.add_transfer(D, *args)


def test_transfers_filters(wctx):
    fl, bank = setup(wctx)
    other = wctx.accounts.create("Payoneer", "USD")
    wctx.accounts.add_transfer(date(2026, 10, 2), fl, other, 1000, 1000)
    wctx.accounts.add_transfer(D, fl, bank, 1000, 3000)
    assert len(wctx.accounts.transfers(start=date(2026, 11, 1))) == 1
    assert len(wctx.accounts.transfers(account_id=other)) == 1
    assert len(wctx.accounts.transfers(account_id=fl)) == 2


def test_received_by_month(wctx):
    fl, _ = setup(wctx)
    wid = wctx.works.create(title="u", started_on=D)
    wctx.works.add_received(wid, 100_000, "USD", date(2026, 3, 9), fl, wctx.fx)
    assert wctx.works.received_by_month(2026) == {3: 100_000, 11: 500_000}
