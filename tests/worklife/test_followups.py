from datetime import UTC, date, datetime, timedelta

import pytest

from prospector import fx
from prospector.worklife import followups

T = date(2026, 11, 4)


def make(ctx, **kw):
    base = dict(title="Go API", client="Acme", source="freelancer", kind="gig", url=None, applied_on=T,
                follow_up_on=T)
    return ctx.apps.create(**(base | kw))


def test_due_lists_open_and_past_dates_only(wctx):
    a = make(wctx, title="today")
    b = make(wctx, title="interview", follow_up_on=T - timedelta(days=1))
    wctx.apps.update(b, stage="interview")
    c = make(wctx, title="won", follow_up_on=T - timedelta(days=3))
    wctx.apps.update(c, stage="won")
    make(wctx, title="tomorrow", follow_up_on=T + timedelta(days=1))
    make(wctx, title="no date", follow_up_on=None)
    assert [x.title for x in followups.due(wctx.apps, T)] == ["interview", "today"]
    assert a


def test_due_uses_tunis_date(wctx):
    make(wctx, title="x", follow_up_on=date(2026, 11, 4))
    assert [x.title for x in followups.due(wctx.apps, fx.today(datetime(2026, 11, 3, 23, 30, tzinfo=UTC)))] == ["x"]


def test_followed_up_moves_date_and_counts(wctx):
    aid = make(wctx)
    a = followups.act(wctx, aid, "followed_up", T)
    assert (a.follow_up_on, a.follow_ups, a.stage) == (T + timedelta(days=7), 1, "waiting")
    assert wctx.apps.events(aid)[-1].kind == "followed_up"


def test_interview_needs_date(wctx):
    aid = make(wctx)
    with pytest.raises(ValueError):
        followups.act(wctx, aid, "interview", T)
    a = followups.act(wctx, aid, "interview", T, on=date(2026, 11, 9), text="Call with CTO")
    assert (a.stage, a.follow_up_on, a.next_step) == ("interview", date(2026, 11, 9), "Call with CTO")


def test_snooze_and_unknown_action(wctx):
    aid = make(wctx)
    assert followups.act(wctx, aid, "snooze", T, on=date(2026, 11, 20)).follow_up_on == date(2026, 11, 20)
    with pytest.raises(ValueError):
        followups.act(wctx, aid, "snooze", T)
    with pytest.raises(ValueError):
        followups.act(wctx, aid, "explode", T)


@pytest.mark.parametrize("stage", ["rejected", "no_reply", "withdrawn", "won"])
def test_closing_stage_clears_follow_up(wctx, stage):
    aid = make(wctx)
    a = followups.act(wctx, aid, stage, T)
    assert (a.stage, a.closed_on, a.follow_up_on) == (stage, T, None)
    assert wctx.apps.events(aid)[-1].kind == "stage"


def test_auto_close_after_followup_and_full_period(wctx):
    old = make(wctx, title="old", follow_up_on=T - timedelta(days=8))
    edge = make(wctx, title="edge", follow_up_on=T - timedelta(days=7))
    never = make(wctx, title="never followed", follow_up_on=T - timedelta(days=30))
    for aid in (old, edge):
        wctx.apps.update(aid, follow_ups=1)
    assert followups.auto_close(wctx, T) == 1
    assert wctx.apps.get(old).stage == "no_reply" and wctx.apps.get(old).closed_on == T
    assert wctx.apps.events(old)[-1].text == "closed: no answer"
    assert wctx.apps.get(edge).stage == "waiting" and wctx.apps.get(never).stage == "waiting"
