import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from prospector.config import Settings
from prospector.context import AppContext
from prospector.expiry import (age_signal, check_freelancer, check_github, check_links, deadline_signal, run_expiry)
from prospector.models import Kind, Status
from prospector.profile.model import Profile, Targets
from prospector.store.db import connect

NOW = datetime(2026, 11, 3, 6, tzinfo=UTC)


@pytest.fixture
def ectx(tmp_path):
    s = Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p", data_dir=tmp_path)
    return AppContext.create(s, connect(":memory:"), Profile(skills={}, projects=[], targets=Targets(kinds=list(Kind), regions=[])),
                             httpx.Client())


def add(ctx, make_lead, url, status=Status.NEW, created=None, **kw):
    lid = ctx.leads.insert(make_lead(canonical_url=url, **kw))
    if status is not Status.NEW:
        ctx.leads.set_status(lid, status)
    if created:
        ctx.conn.execute("UPDATE leads SET created_at = ? WHERE id = ?", (created.isoformat(), lid))
    return lid


# --- rules -----------------------------------------------------------------------------------------------

def test_deadline_signal(make_lead):
    assert deadline_signal(make_lead(deadline=date(2026, 11, 2)), NOW).reason == "Deadline passed (2026-11-02)."
    assert deadline_signal(make_lead(deadline=date(2026, 11, 3)), NOW) is None  # still today
    assert deadline_signal(make_lead(), NOW) is None


@pytest.mark.parametrize("kind, days, expired", [(Kind.GIG, 15, True), (Kind.GIG, 13, False), (Kind.BOUNTY, 15, True),
                                                 (Kind.JOB, 46, True), (Kind.CONTRACT, 44, False),
                                                 (Kind.PFE, 61, True), (Kind.AI_TRAINING, 59, False)])
def test_age_signal_by_kind(ectx, make_lead, kind, days, expired):
    lead = make_lead(kind=kind, posted_at=NOW - timedelta(days=days))
    sig = age_signal(lead, None, NOW, ectx.settings)
    assert (sig is not None) is expired
    if sig:
        assert sig.reason == f"Posted {days} days ago."


def test_age_uses_first_seen_without_posting_date(ectx, make_lead):
    sig = age_signal(make_lead(kind=Kind.GIG), (NOW - timedelta(days=20)).isoformat(), NOW, ectx.settings)
    assert sig.reason == "First seen 20 days ago."


# --- run_expiry ------------------------------------------------------------------------------------------

def test_new_lead_expires_and_leaves_new_tab(ectx, make_lead):
    lid = add(ectx, make_lead, "https://e/1", deadline=date(2026, 10, 1))
    assert run_expiry(ectx, NOW) == 1
    row = ectx.leads.get_row(lid)
    assert row.lead.status is Status.EXPIRED and row.closed_reason == "Deadline passed (2026-10-01)."
    assert ectx.leads.list(Status.NEW) == [] and len(ectx.leads.list(Status.EXPIRED)) == 1


def test_filtered_lead_keeps_its_filter_reason(ectx, make_lead):
    lid = add(ectx, make_lead, "https://e/1", deadline=date(2026, 10, 1))
    ectx.leads.set_status(lid, Status.FILTERED, "unpaid")
    run_expiry(ectx, NOW)
    assert ectx.leads.get(lid).status is Status.EXPIRED and ectx.leads.get(lid).filter_reason == "unpaid"


@pytest.mark.parametrize("status", [Status.STARRED, Status.APPLIED])
def test_starred_and_applied_only_flagged(ectx, make_lead, status):
    lid = add(ectx, make_lead, "https://e/1", status=status, deadline=date(2026, 10, 1))
    run_expiry(ectx, NOW)
    row = ectx.leads.get_row(lid)
    assert row.lead.status is status and row.closed_reason == "Deadline passed (2026-10-01)."


def test_dismissed_untouched(ectx, make_lead):
    lid = add(ectx, make_lead, "https://e/1", status=Status.DISMISSED, deadline=date(2026, 10, 1))
    assert run_expiry(ectx, NOW) == 0 and ectx.leads.get_row(lid).closed_reason is None


def test_reset_is_not_expired_again_for_same_reason(ectx, make_lead):
    lid = add(ectx, make_lead, "https://e/1", deadline=date(2026, 10, 1))
    run_expiry(ectx, NOW)
    ectx.expiry.keep_open(lid)
    ectx.leads.set_status(lid, Status.NEW)
    assert run_expiry(ectx, NOW) == 0
    row = ectx.leads.get_row(lid)
    assert row.lead.status is Status.NEW and row.closed_reason is None


def test_reset_but_different_reason_expires(ectx, make_lead):
    lid = add(ectx, make_lead, "https://e/1", deadline=date(2026, 10, 1), kind=Kind.GIG)
    run_expiry(ectx, NOW)
    ectx.expiry.keep_open(lid)
    ectx.leads.set_status(lid, Status.NEW)
    ectx.conn.execute("UPDATE leads SET posted_at = ? WHERE id = ?", ((NOW - timedelta(days=30)).isoformat(), lid))
    assert run_expiry(ectx, NOW) == 1 and ectx.leads.get(lid).status is Status.EXPIRED


def test_idempotent(ectx, make_lead):
    add(ectx, make_lead, "https://e/1", deadline=date(2026, 10, 1))
    assert run_expiry(ectx, NOW) == 1 and run_expiry(ectx, NOW) == 0


# --- source checks ---------------------------------------------------------------------------------------

def freelancer_api(statuses):
    def handler(request):
        assert request.url.host == "www.freelancer.com"
        ids = request.url.params.get_list("projects[]")
        projects = [{"id": int(i), **statuses[int(i)]} for i in ids if int(i) in statuses]
        return httpx.Response(200, json={"result": {"projects": projects}})
    return handler


def test_freelancer_closed(ectx, make_lead):
    a = add(ectx, make_lead, "https://www.freelancer.com/projects/a", sources=["freelancer"])
    b = add(ectx, make_lead, "https://www.freelancer.com/projects/b", sources=["freelancer"])
    c = add(ectx, make_lead, "https://www.freelancer.com/projects/c", sources=["freelancer"])
    ectx.expiry.add_ref(a, "freelancer", "101")
    ectx.expiry.add_ref(b, "freelancer", "102")
    ectx.leads.put_raw(c, "freelancer", json.dumps({"id": 103}))  # older leads: id from the raw payload
    http = httpx.Client(transport=httpx.MockTransport(freelancer_api({
        101: {"status": "closed", "frontend_project_status": "complete"},
        102: {"status": "active", "frontend_project_status": "open"},
        103: {"status": "active", "frontend_project_status": "work_in_progress"}})))
    found = dict(check_freelancer(ectx, http))
    assert found[a].reason == "Closed on Freelancer." and found[c].reason == "Awarded on Freelancer."
    assert b not in found


def test_github_closed(ectx, make_lead):
    a = add(ectx, make_lead, "https://github.com/acme/app/issues/7", sources=["github_bounties"])
    b = add(ectx, make_lead, "https://github.com/acme/app/issues/8", sources=["github_bounties"])

    def handler(request):
        n = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, json={"state": "closed" if n == "7" else "open"})
    found = dict(check_github(ectx, httpx.Client(transport=httpx.MockTransport(handler)), token="t"))
    assert found[a].reason == "Issue closed on GitHub." and b not in found


def test_source_check_errors_are_ignored(ectx, make_lead):
    a = add(ectx, make_lead, "https://github.com/acme/app/issues/7", sources=["github_bounties"])
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert dict(check_github(ectx, http, token="t")) == {}
    assert a


def test_run_expiry_uses_source_checks(ectx, make_lead, monkeypatch):
    a = add(ectx, make_lead, "https://github.com/acme/app/issues/7", sources=["github_bounties"])
    monkeypatch.setattr("prospector.expiry.check_github", lambda ctx, http, token: [(a, __import__("prospector.expiry", fromlist=["Signal"]).Signal("github", "Issue closed on GitHub."))])
    ectx.settings.github_token = __import__("pydantic").SecretStr("t")
    assert run_expiry(ectx, NOW) == 1 and ectx.leads.get_row(a).closed_reason == "Issue closed on GitHub."


# --- weekly link check -----------------------------------------------------------------------------------

def test_link_check_flags_gone_pages(ectx, make_lead, monkeypatch):
    gone = add(ectx, make_lead, "https://e/gone", status=Status.STARRED)
    alive = add(ectx, make_lead, "https://e/alive", status=Status.APPLIED)
    new = add(ectx, make_lead, "https://e/new")
    seen = []

    def fake(url):
        seen.append(url)
        return url.endswith("gone")
    monkeypatch.setattr("prospector.expiry.page_gone", fake)
    assert check_links(ectx, NOW) == 1
    assert ectx.leads.get_row(gone).closed_reason == "The posting page is gone (404)."
    assert ectx.leads.get_row(gone).lead.status is Status.STARRED
    assert ectx.leads.get_row(alive).closed_reason is None and "https://e/new" not in seen and new
