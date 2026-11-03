from datetime import UTC, datetime, timedelta

import numpy as np

from prospector.models import Kind, Pay, Status
from prospector.store.db import connect
from prospector.store.feedback import FeedbackRepo
from prospector.store.health import HealthRepo
from prospector.store.kv import KV
from prospector.store.leads import LeadRepo
from prospector.store.scores import ScoreRepo


def repos():
    conn = connect(":memory:")
    return conn, LeadRepo(conn), ScoreRepo(conn)


def test_insert_and_get_roundtrip(make_lead):
    _, leads, _ = repos()
    lid = leads.insert(make_lead(pay=Pay(1000, 2000, "EUR", "month"), locations=["Paris"], languages=["fr", "en"]))
    got = leads.get(lid)
    assert got.id == lid
    assert got.pay == Pay(1000, 2000, "EUR", "month")
    assert got.locations == ["Paris"] and got.languages == ["fr", "en"]
    assert got.kind is Kind.JOB and got.status is Status.NEW


def test_add_source_merges(make_lead):
    _, leads, _ = repos()
    lid = leads.insert(make_lead())
    leads.add_source(lid, "himalayas")
    leads.add_source(lid, "himalayas")
    assert leads.get(lid).sources == ["remotive", "himalayas"]


def test_by_canonical_url_and_recent_by_company(make_lead):
    _, leads, _ = repos()
    lid = leads.insert(make_lead(company="ACME Inc."))
    assert leads.by_canonical_url("https://example.com/1").id == lid
    assert [l.id for l in leads.recent_by_company("acme")] == [lid]


def test_list_filters_by_tab_and_kind(make_lead):
    _, leads, scores = repos()
    a = leads.insert(make_lead(canonical_url="u1", kind=Kind.GIG))
    b = leads.insert(make_lead(canonical_url="u2", kind=Kind.JOB))
    leads.set_status(b, Status.STARRED)
    scores.save_stage1(a, 0.8, {"final": 0.8})
    assert [r.lead.id for r in leads.list(Status.NEW)] == [a]
    assert [r.lead.id for r in leads.list(Status.STARRED)] == [b]
    assert leads.list(Status.NEW, kind=Kind.JOB) == []
    assert leads.list(Status.NEW)[0].stage1 == 0.8


def test_set_status_with_reason(make_lead):
    _, leads, _ = repos()
    lid = leads.insert(make_lead())
    leads.set_status(lid, Status.FILTERED, "unpaid")
    got = leads.get(lid)
    assert got.status is Status.FILTERED and got.filter_reason == "unpaid"


def test_top_unreviewed_respects_threshold_and_limit(make_lead):
    _, leads, scores = repos()
    ids = [leads.insert(make_lead(canonical_url=f"u{i}")) for i in range(5)]
    for i, lid in enumerate(ids):
        scores.save_stage1(lid, 0.1 * (i + 3), {})
    scores.save_stage2(ids[4], {"verdict": "strong"})
    assert scores.top_unreviewed(threshold=0.45, limit=2) == [ids[3], ids[2]]


def test_embeddings_roundtrip(make_lead):
    _, leads, scores = repos()
    lid = leads.insert(make_lead())
    scores.save_embedding(lid, np.array([0.6, 0.8], dtype=np.float32))
    assert np.allclose(scores.embeddings([lid]), [[0.6, 0.8]])
    assert scores.embeddings([]).shape[0] == 0


def test_new_since_and_deadlines(make_lead):
    _, leads, scores = repos()
    now = datetime(2026, 11, 3, 8, tzinfo=UTC)
    a = leads.insert(make_lead(canonical_url="a"))
    scores.save_stage1(a, 0.5, {})
    assert [r.lead.id for r in leads.new_since(now - timedelta(days=1), limit=10)] == [a]
    assert leads.new_since(now + timedelta(days=1), limit=10) == []
    s = leads.insert(make_lead(canonical_url="s", deadline=now.date() + timedelta(days=2)))
    leads.set_status(s, Status.STARRED)
    assert [r.lead.id for r in leads.starred_with_deadline_within(3, now.date())] == [s]


def test_record_failure_counts_and_success_resets():
    conn = connect(":memory:")
    h = HealthRepo(conn)
    for _ in range(3):
        st = h.record_failure("remotive", "boom")
    assert st.consecutive_failures == 3 and st.last_error == "boom"
    h.record_success("remotive", 12, drift=False)
    st = h.get("remotive")
    assert st.consecutive_failures == 0 and st.last_count == 12 and not st.paused


def test_feedback_latest_action_wins(make_lead):
    conn, leads, _ = repos()
    lid = leads.insert(make_lead())
    fb = FeedbackRepo(conn)
    fb.record(lid, "star")
    fb.record(lid, "dismiss")
    assert fb.negative_ids() == [lid] and fb.positive_ids() == []
    assert fb.count() == 2


def test_prune_raw_older_than_30_days(make_lead):
    conn, leads, _ = repos()
    lid = leads.insert(make_lead())
    leads.put_raw(lid, "remotive", "{}")
    conn.execute("UPDATE raw_payloads SET stored_at = datetime('now', '-31 days')")
    leads.put_raw(lid, "remotive", "{}")
    assert leads.prune_raw(30) == 1


def test_kv_roundtrip():
    kv = KV(connect(":memory:"))
    assert kv.get("x", 5) == 5
    kv.set("x", {"a": [1, 2]})
    assert kv.get("x") == {"a": [1, 2]}


def test_connect_is_idempotent(tmp_path):
    p = tmp_path / "db.sqlite"
    connect(p).close()
    conn = connect(p)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
