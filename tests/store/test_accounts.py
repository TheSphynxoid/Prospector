from datetime import date

import pytest


def test_archived_account_keeps_payments(wctx):
    acc = wctx.accounts.create("Payoneer", "USD")
    wid = wctx.works.create(title="t", currency="USD", started_on=date(2026, 11, 4))
    wctx.works.add_received(wid, 1000, "USD", date(2026, 11, 4), acc, wctx.fx)
    wctx.accounts.archive(acc)
    assert wctx.accounts.list() == [] and [a.id for a in wctx.accounts.list(include_archived=True)] == [acc]
    assert wctx.accounts.get(acc).archived and wctx.works.payments(wid)[0].account_id == acc


def test_account_currency_validated(wctx):
    with pytest.raises(ValueError):
        wctx.accounts.create("Yen", "JPY")
    wctx.accounts.create("Payoneer", "USD")
    with pytest.raises(ValueError):
        wctx.accounts.create("Payoneer", "EUR")
    with pytest.raises(ValueError):
        wctx.accounts.create("  ", "USD")


def test_last_used(wctx):
    a, b = wctx.accounts.create("A", "USD"), wctx.accounts.create("B", "USD")
    assert wctx.accounts.last_used() is None
    wid = wctx.works.create(title="t", currency="USD", started_on=date(2026, 11, 4))
    wctx.works.add_received(wid, 1000, "USD", date(2026, 11, 1), b, wctx.fx)
    wctx.works.add_received(wid, 1000, "USD", date(2026, 10, 1), a, wctx.fx)
    assert wctx.accounts.last_used().id == b
