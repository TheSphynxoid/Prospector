"""The extra lead filters the agent API uses: several kinds, location, since, verdict, has-email, body search."""
from datetime import UTC, datetime

import pytest

from prospector.models import Kind, Status
from prospector.store.db import connect
from prospector.store.leads import LeadRepo
from prospector.store.scores import ScoreRepo


@pytest.fixture
def repo(make_lead):
    conn = connect(":memory:")
    leads, scores = LeadRepo(conn), ScoreRepo(conn)
    a = leads.insert(make_lead(canonical_url="https://e/a", title="Go backend PFE", kind=Kind.PFE,
                               locations=["Tunis, Tunisie"], body="Postuler : jobs@acme.tn",
                               posted_at=datetime(2026, 11, 5, tzinfo=UTC)))
    b = leads.insert(make_lead(canonical_url="https://e/b", title="Data internship", kind=Kind.INTERNSHIP,
                               locations=["Sfax, Tunisie"], body="Apply on https://acme.tn/careers using Kubernetes",
                               posted_at=datetime(2026, 10, 1, tzinfo=UTC)))
    leads.insert(make_lead(canonical_url="https://e/c", title="Senior job", kind=Kind.JOB, locations=["Paris"],
                           posted_at=datetime(2026, 11, 6, tzinfo=UTC)))
    scores.save_stage1(a, 0.7, {})
    scores.save_stage2(a, {"verdict": "strong", "fit_summary": "fits", "red_flags": []})
    scores.save_stage1(b, 0.5, {})
    scores.save_stage2(b, {"verdict": "weak", "fit_summary": "meh", "red_flags": []})
    return leads


def _titles(rows):
    return {r.lead.title for r in rows}


def test_several_kinds(repo):
    assert _titles(repo.list(Status.NEW, kind=[Kind.PFE, Kind.INTERNSHIP])) == {"Go backend PFE", "Data internship"}


def test_location_matches_any_part_case_insensitively(repo):
    assert _titles(repo.list(Status.NEW, location="sfax")) == {"Data internship"}
    assert _titles(repo.list(Status.NEW, location="TUNISIE")) == {"Go backend PFE", "Data internship"}


def test_location_with_accents(repo, make_lead):
    repo.insert(make_lead(canonical_url="https://e/m", title="South", locations=["Médenine, Tunisie"]))
    assert _titles(repo.list(Status.NEW, location="Médenine")) == {"South"}


def test_since_uses_posting_date(repo):
    since = datetime(2026, 11, 1, tzinfo=UTC)
    assert _titles(repo.list(Status.NEW, since=since)) == {"Go backend PFE", "Senior job"}


def test_verdict(repo):
    assert _titles(repo.list(Status.NEW, verdict="strong")) == {"Go backend PFE"}


def test_has_email(repo):
    assert _titles(repo.list(Status.NEW, has_email=True)) == {"Go backend PFE"}


def test_deep_search_reads_the_body(repo):
    assert _titles(repo.list(Status.NEW, q="kubernetes")) == set()
    assert _titles(repo.list(Status.NEW, q="kubernetes", deep=True)) == {"Data internship"}


def test_count_agrees_with_list(repo):
    assert repo.count(Status.NEW, kind=[Kind.PFE, Kind.INTERNSHIP], location="tunisie", has_email=True) == 1
