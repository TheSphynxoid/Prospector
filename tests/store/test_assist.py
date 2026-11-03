import pytest

from prospector.store.assist import AssistRepo, AssistRow
from prospector.store.db import connect
from prospector.store.leads import LeadRepo


@pytest.fixture
def db():
    return connect(":memory:")


@pytest.fixture
def lid(db, make_lead):
    return LeadRepo(db).insert(make_lead())


def test_recent_skips_errors_and_keeps_order(db, lid):
    repo = AssistRepo(db)
    for i in range(25):
        repo.add(lid, "user" if i % 2 == 0 else "assistant", f"m{i}")
        repo.add(lid, "error", f"e{i}")
    recent = repo.recent(lid, 20)
    assert [m.content for m in recent] == [f"m{i}" for i in range(5, 25)]
    assert len(repo.messages(lid)) == 50


def test_clear_removes_messages_and_bid(db, lid):
    repo = AssistRepo(db)
    repo.add(lid, "user", "hi")
    repo.set_bid(lid, {"proposal": "p"})
    repo.set_posting(lid, "full text", "pasted")
    repo.clear(lid)
    assert repo.messages(lid) == [] and repo.get(lid).bid is None
    assert repo.get(lid).posting == "full text"  # the posting is not part of the chat


def test_get_defaults_when_missing(db, lid):
    assert AssistRepo(db).get(lid) == AssistRow(None, None, None, False, None)


def test_cascade_on_lead_delete(db, lid):
    repo = AssistRepo(db)
    repo.add(lid, "user", "hi")
    repo.set_bid(lid, {"proposal": "p"})
    db.execute("DELETE FROM leads WHERE id = ?", (lid,))
    assert db.execute("SELECT COUNT(*) FROM lead_messages").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM lead_assist").fetchone()[0] == 0


def test_set_fetch_result_marks_tried(db, lid):
    repo = AssistRepo(db)
    repo.set_fetch_result(lid, None, None, "The page needs a login")
    row = repo.get(lid)
    assert row.fetch_tried and row.fetch_note == "The page needs a login" and row.posting is None
    repo.set_fetch_result(lid, "text", "fetched", None)
    assert repo.get(lid) == AssistRow("text", "fetched", None, True, None)


def test_set_posting_replaces(db, lid):
    repo = AssistRepo(db)
    repo.set_posting(lid, "a", "fetched")
    repo.set_posting(lid, "b", "pasted")
    assert (repo.get(lid).posting, repo.get(lid).posting_origin) == ("b", "pasted")


def test_add_returns_message(db, lid):
    m = AssistRepo(db).add(lid, "user", "hi")
    assert (m.lead_id, m.role, m.content) == (lid, "user", "hi") and m.id and m.at
