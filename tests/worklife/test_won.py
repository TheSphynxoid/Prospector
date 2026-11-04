from datetime import date

from prospector.models import Kind, Pay
from prospector.worklife import followups

T = date(2026, 11, 4)


def applied(ctx, make_lead, pay):
    from prospector.worklife.flows import on_applied
    lid = ctx.leads.insert(make_lead(title="Go booking API", company="Voyages", kind=Kind.GIG, pay=pay))
    return lid, on_applied(ctx, lid, T)


def test_won_creates_work_with_fixed_price(wctx, make_lead):
    lid, aid = applied(wctx, make_lead, Pay(650, 650, "USD", "fixed"))
    a = followups.act(wctx, aid, "won", T)
    w = wctx.works.by_application(aid)
    assert a.stage == "won"
    assert (w.title, w.client, w.kind, w.lead_id, w.price_milli, w.currency, w.started_on, w.stage) == \
        ("Go booking API", "Voyages", "gig", lid, 650_000, "USD", T, "in_progress")


def test_won_one_bound_price(wctx, make_lead):
    _, aid = applied(wctx, make_lead, Pay(None, 300, "EUR", "fixed"))
    followups.act(wctx, aid, "won", T)
    w = wctx.works.by_application(aid)
    assert (w.price_milli, w.currency) == (300_000, "EUR")


def test_won_range_or_hourly_price_left_empty(wctx, make_lead):
    from prospector.worklife.flows import on_applied
    pays = (Pay(250, 750, "USD", "fixed"), Pay(20, 20, "USD", "hour"), None, Pay(5, 5, "JPY", "fixed"))
    for i, pay in enumerate(pays):
        lid = wctx.leads.insert(make_lead(canonical_url=f"https://e/{i}", pay=pay))
        aid = on_applied(wctx, lid, T)
        followups.act(wctx, aid, "won", T)
        w = wctx.works.by_application(aid)
        assert w.price_milli is None and w.currency == "USD", pay


def test_won_twice_one_work(wctx, make_lead):
    from prospector.worklife.flows import on_won
    _, aid = applied(wctx, make_lead, None)
    first = on_won(wctx, aid, T)
    assert on_won(wctx, aid, T) == first and len(wctx.works.list()) == 1


def test_won_manual_application(wctx):
    from prospector.worklife.flows import on_won
    aid = wctx.apps.create(title="Referral site", client="Cousin", applied_on=T)
    w = wctx.works.get(on_won(wctx, aid, T))
    assert (w.title, w.lead_id, w.price_milli, w.currency) == ("Referral site", None, None, "USD")
