import sqlite3
from datetime import date

import pytest

D = date(2026, 11, 4)


def make(ctx, **kw):
    base = dict(title="Go API", client="Acme", source="freelancer", kind="gig", url="https://e/1",
                applied_on=D, follow_up_on=date(2026, 11, 11))
    return ctx.apps.create(**(base | kw))


def test_create_writes_applied_event(wctx):
    aid = make(wctx)
    a = wctx.apps.get(aid)
    assert (a.title, a.stage, a.applied_on, a.follow_up_on, a.follow_ups, a.from_lead_action) == \
        ("Go API", "waiting", D, date(2026, 11, 11), 0, False)
    assert [e.kind for e in wctx.apps.events(aid)] == ["applied"]


def test_one_application_per_lead(wctx, make_lead):
    lid = wctx.leads.insert(make_lead())
    make(wctx, lead_id=lid)
    with pytest.raises(sqlite3.IntegrityError):
        make(wctx, lead_id=lid)
    assert wctx.apps.by_lead(lid).lead_id == lid
    make(wctx), make(wctx)  # several manual ones (no lead) are fine


def test_list_filters_and_sources(wctx):
    make(wctx, title="a"), make(wctx, title="b", source="keejob")
    wctx.apps.update(make(wctx, title="c"), stage="rejected")
    assert {a.title for a in wctx.apps.list(stage="waiting")} == {"a", "b"}
    assert [a.title for a in wctx.apps.list(source="keejob")] == ["b"]
    assert wctx.apps.sources() == ["freelancer", "keejob"]


def test_delete_removes_events(wctx):
    aid = make(wctx)
    wctx.apps.add_event(aid, "note", "hi")
    wctx.apps.delete(aid)
    assert wctx.apps.get(aid) is None and wctx.apps.events(aid) == []


def test_counts_since(wctx):
    make(wctx, applied_on=date(2026, 9, 1))  # too old
    make(wctx)  # waiting
    wctx.apps.update(make(wctx), stage="interview")
    wctx.apps.update(make(wctx), stage="won")
    wctx.apps.update(make(wctx), stage="no_reply")
    wctx.apps.update(make(wctx), stage="rejected")
    assert wctx.apps.counts_since(date(2026, 10, 5)) == {"sent": 5, "replied": 3, "won": 1}
