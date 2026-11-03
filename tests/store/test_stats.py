from datetime import UTC, date, datetime, timedelta

import pytest

from prospector.models import Kind, Status
from prospector.store.db import connect
from prospector.store.kv import KV
from prospector.store.leads import LeadRepo
from prospector.store.stats import StatsRepo

# 12:00 Tunis on 3 Nov; Tunis is UTC+1 all year
NOW = datetime(2026, 11, 3, 11, tzinfo=UTC)


@pytest.fixture
def db():
    return connect(":memory:")


def add(db, make_lead, url, created_at, kind=Kind.JOB, sources=("remotive",), status=Status.NEW):
    lid = LeadRepo(db).insert(make_lead(canonical_url=url, kind=kind, sources=list(sources), status=status))
    db.execute("UPDATE leads SET created_at = ? WHERE id = ?", (created_at.isoformat(), lid))
    return lid


def test_empty_database(db):
    o = StatsRepo(db).overview(NOW)
    assert (o.new_today, o.new_week, o.starred, o.applied, o.llm_used) == (0, 0, 0, 0, 0)
    assert len(o.per_day) == 14 and all(n == 0 for _, n in o.per_day)
    assert o.per_day[-1][0] == date(2026, 11, 3)
    assert o.by_source == [] and o.by_kind == []


def test_counts_bucket_by_tunis_day(db, make_lead):
    add(db, make_lead, "a", NOW)
    add(db, make_lead, "b", datetime(2026, 11, 2, 23, 30, tzinfo=UTC))  # 00:30 on 3 Nov in Tunis
    add(db, make_lead, "c", datetime(2026, 11, 2, 22, 30, tzinfo=UTC))  # 23:30 on 2 Nov in Tunis
    add(db, make_lead, "d", NOW - timedelta(days=10))
    add(db, make_lead, "old", NOW - timedelta(days=30))
    o = StatsRepo(db).overview(NOW)
    days = dict(o.per_day)
    assert o.new_today == 2 and days[date(2026, 11, 3)] == 2
    assert days[date(2026, 11, 2)] == 1 and days[date(2026, 10, 24)] == 1
    assert o.new_week == 3
    assert sum(days.values()) == 4  # the 30-day-old lead is outside the window


def test_status_counts_are_all_time(db, make_lead):
    add(db, make_lead, "s", NOW - timedelta(days=40), status=Status.STARRED)
    add(db, make_lead, "a1", NOW, status=Status.APPLIED)
    add(db, make_lead, "a2", NOW, status=Status.APPLIED)
    o = StatsRepo(db).overview(NOW)
    assert (o.starred, o.applied) == (1, 2)
    assert o.new_today == 2  # "new today" counts arrivals, whatever their status now


def test_breakdowns_skip_filtered_and_sort_desc(db, make_lead):
    add(db, make_lead, "1", NOW, kind=Kind.BOUNTY, sources=["github_bounties"])
    add(db, make_lead, "2", NOW, sources=["remotive", "hn"])
    add(db, make_lead, "3", NOW, sources=["hn"])
    add(db, make_lead, "4", NOW, sources=["hn"], status=Status.FILTERED)
    o = StatsRepo(db).overview(NOW)
    assert o.by_source == [("hn", 2), ("github_bounties", 1), ("remotive", 1)]
    assert o.by_kind == [("job", 2), ("bounty", 1)]


def test_llm_used_reads_todays_utc_counter(db):
    KV(db).set("llm_calls:2026-11-03", 7)
    KV(db).set("llm_calls:2026-11-02", 20)
    assert StatsRepo(db).overview(NOW).llm_used == 7
