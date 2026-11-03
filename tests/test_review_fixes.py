"""Regression tests for the final-review findings."""
import threading
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
import respx

from prospector.config import Settings
from prospector.llm.client import LLMClient
from prospector.models import Kind
from prospector.profile.model import Profile, Project, Targets
from prospector.rank.stage2 import run_stage2
from prospector.sources.runner import run_source, should_run
from prospector.store.db import connect
from prospector.store.health import HealthRepo, SourceHealth
from prospector.store.kv import KV
from prospector.store.leads import LeadRepo
from prospector.store.mail import MailRepo
from prospector.store.scores import ScoreRepo

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)
BASE = "https://llm.test/v1"


# Important 1 — secrets in query strings must not reach health/last_error (shown in digest + dashboard)
@respx.mock
def test_source_error_does_not_store_query_secrets():
    class Leaky:
        id, interval_hours = "adzuna", 6

        def fetch(self, http):
            r = http.get("https://api.adzuna.com/v1/api/jobs/fr/search/1?app_id=ID&app_key=SUPERSECRET")
            r.raise_for_status()
            return []

    respx.get(url__startswith="https://api.adzuna.com").mock(return_value=httpx.Response(401))
    health = HealthRepo(connect(":memory:"))
    with httpx.Client() as http:
        run_source(Leaky(), http, health, NOW)
    err = health.get("adzuna").last_error
    assert "SUPERSECRET" not in err and "401" in err


# Important 2 — failing leads must not drain the daily LLM cap
def _seed(make_lead, n):
    conn = connect(":memory:")
    leads, scores = LeadRepo(conn), ScoreRepo(conn)
    for i in range(n):
        lid = leads.insert(make_lead(canonical_url=f"u{i}", content_hash=f"h{i}"))
        scores.save_stage1(lid, 0.9, {})
    return conn, leads, scores


PROF = Profile(skills={"go": 1}, projects=[Project(name="P", writeup="w")], targets=Targets(kinds=list(Kind), regions=[]))


@respx.mock
def test_unparseable_lead_not_retried_same_day(make_lead):
    route = respx.post(f"{BASE}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "no json"}}]}))
    conn, leads, scores = _seed(make_lead, 1)
    kv, today = KV(conn), date(2026, 11, 3)
    with httpx.Client() as http:
        client = LLMClient(BASE, "k", "m", http)
        run_stage2(leads, scores, kv, client, PROF, cap=20, threshold=0.5, today=today)
        run_stage2(leads, scores, kv, client, PROF, cap=20, threshold=0.5, today=today)
    assert route.call_count == 2  # one review + one repair, then skipped for the day
    assert kv.get(f"llm_calls:{today}") == 1


@respx.mock
def test_transport_errors_do_not_charge_cap(make_lead):
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(503))
    conn, leads, scores = _seed(make_lead, 5)
    kv, today = KV(conn), date(2026, 11, 3)
    with httpx.Client() as http:
        run_stage2(leads, scores, kv, LLMClient(BASE, "k", "m", http), PROF, cap=20, threshold=0.5, today=today)
    assert kv.get(f"llm_calls:{today}", 0) == 0


# Important 3 — fetch duration must not push sources a whole tick late
def test_should_run_tolerates_fetch_duration():
    class S:
        id, interval_hours = "alerts", 0.25
    h = SourceHealth("alerts", last_run=(NOW - timedelta(minutes=15) + timedelta(seconds=20)).isoformat())
    assert should_run(h, S(), NOW)


# Important 4 — ids returned by insert must belong to the inserted row under concurrency
def test_insert_ids_consistent_across_threads(make_lead, tmp_path):
    conn = connect(tmp_path / "db.sqlite")
    leads, mail = LeadRepo(conn), MailRepo(conn)
    errors = []

    def lead_writer(t):
        try:
            for i in range(200):
                url = f"https://x/{t}/{i}"
                lid = leads.insert(make_lead(canonical_url=url))
                if leads.get(lid).canonical_url != url:
                    errors.append((url, lid))
        except Exception as e:  # surface thread failures to the test
            errors.append(repr(e))

    def mail_writer():
        try:
            for _ in range(400):
                mail.insert(b"raw", NOW)
        except Exception as e:
            errors.append(repr(e))

    threads = [threading.Thread(target=lead_writer, args=(t,)) for t in range(3)] + \
              [threading.Thread(target=mail_writer) for _ in range(3)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == []


# Promoted minor — an empty/short bridge secret must stop the server from starting
def test_check_secrets_rejects_short_bridge_secret(tmp_path):
    from prospector.__main__ import check_secrets
    s = Settings(_env_file=None, llm_api_key="k", bridge_secret="", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p")
    with pytest.raises(SystemExit):
        check_secrets(s)
    check_secrets(s.model_copy(update={"bridge_secret": s.bridge_secret.__class__("x" * 32)}))

