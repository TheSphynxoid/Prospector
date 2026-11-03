import json
from datetime import date

import httpx
import pytest
import respx

from prospector.llm.client import LLMClient, extract_json
from prospector.models import Kind
from prospector.profile.model import Profile, Project, Targets
from prospector.rank.stage2 import review, run_stage2
from prospector.store.db import connect
from prospector.store.kv import KV
from prospector.store.leads import LeadRepo
from prospector.store.scores import ScoreRepo

BASE = "https://llm.test/v1"
GOOD = {"verdict": "strong", "fit_summary": "Fits.", "lead_with_project": "Room mapping",
        "red_flags": [], "pay_estimate": None}


def reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def client():
    with httpx.Client() as http:
        yield LLMClient(BASE, "key", "glm-5.3-flash", http)


@pytest.fixture
def prof():
    return Profile(skills={"go": 1}, projects=[Project(name="Room mapping", writeup="w")],
                   targets=Targets(kinds=list(Kind), regions=[]))


@respx.mock
def test_complete_sends_headers(client):
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=reply("hi"))
    assert client.complete("sys", "user", "sess-1") == "hi"
    req = route.calls.last.request
    assert req.headers["x-opencode-session"] == "sess-1"
    assert req.headers["User-Agent"].startswith("prospector/")
    assert req.headers["Authorization"] == "Bearer key"
    assert json.loads(req.content)["temperature"] == 0


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert extract_json('Sure! {"a":1} hope this helps') == {"a": 1}
    with pytest.raises(ValueError):
        extract_json("no json here")


@respx.mock
def test_review_repairs_once_then_succeeds(client, prof, make_lead):
    route = respx.post(f"{BASE}/chat/completions").mock(side_effect=[reply("I think it fits!"), reply(json.dumps(GOOD))])
    res = review(make_lead(), prof, client, KV(connect(":memory:")), "s")
    assert res.verdict == "strong" and route.call_count == 2


@respx.mock
def test_review_returns_none_after_failed_repair(client, prof, make_lead):
    route = respx.post(f"{BASE}/chat/completions").mock(side_effect=[reply("nope"), reply('{"verdict": "great"}')])
    assert review(make_lead(), prof, client, KV(connect(":memory:")), "s") is None
    assert route.call_count == 2


@respx.mock
def test_review_uses_cache(client, prof, make_lead):
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=reply(json.dumps(GOOD)))
    kv = KV(connect(":memory:"))
    review(make_lead(), prof, client, kv, "s")
    review(make_lead(), prof, client, kv, "s")
    assert route.call_count == 1


@respx.mock
def test_http_error_leaves_lead_unreviewed(client, prof, make_lead):
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(503))
    assert review(make_lead(), prof, client, KV(connect(":memory:")), "s") is None


def seeded(make_lead, n):
    conn = connect(":memory:")
    leads, scores = LeadRepo(conn), ScoreRepo(conn)
    for i in range(n):
        lid = leads.insert(make_lead(canonical_url=f"u{i}", content_hash=f"h{i}"))
        scores.save_stage1(lid, 0.9, {})
    return conn, leads, scores


@respx.mock
def test_run_stage2_respects_daily_cap(client, prof, make_lead):
    respx.post(f"{BASE}/chat/completions").mock(return_value=reply(json.dumps(GOOD)))
    conn, leads, scores = seeded(make_lead, 30)
    kv = KV(conn)
    today = date(2026, 11, 3)
    assert run_stage2(leads, scores, kv, client, prof, cap=20, threshold=0.5, today=today) == 20
    assert run_stage2(leads, scores, kv, client, prof, cap=20, threshold=0.5, today=today) == 0
    assert len(scores.top_unreviewed(0.5, 100)) == 10


@respx.mock
def test_run_stage2_continues_after_failure(client, prof, make_lead):
    respx.post(f"{BASE}/chat/completions").mock(
        side_effect=[httpx.Response(503), reply(json.dumps(GOOD))])
    conn, leads, scores = seeded(make_lead, 2)
    assert run_stage2(leads, scores, KV(conn), client, prof, cap=20, threshold=0.5, today=date(2026, 11, 3)) == 1
