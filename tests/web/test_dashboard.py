from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from prospector.models import Status
from tests.web.conftest import TAILNET


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


def test_list_tabs(ctx, client, make_lead):
    a = ctx.leads.insert(make_lead(canonical_url="a", title="Alpha Go role"))
    b = ctx.leads.insert(make_lead(canonical_url="b", title="Beta C++ role"))
    ctx.leads.set_status(b, Status.STARRED)
    new = client.get("/?tab=new").text
    starred = client.get("/?tab=starred").text
    assert "Alpha Go role" in new and "Beta C++ role" not in new
    assert "Beta C++ role" in starred and "Alpha Go role" not in starred
    assert a


def test_list_escapes_html(ctx, client, make_lead):
    ctx.leads.insert(make_lead(title="<script>alert(1)</script>"))
    assert "<script>alert(1)</script>" not in client.get("/").text


def test_star_action_returns_row_and_records_feedback(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead(title="Gamma role"))
    r = client.post(f"/lead/{lid}/star")
    assert r.status_code == 200 and "Gamma role" in r.text
    assert ctx.leads.get(lid).status is Status.STARRED
    assert ctx.feedback.positive_ids() == [lid]


def test_reset_action_returns_to_new(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    client.post(f"/lead/{lid}/dismiss")
    client.post(f"/lead/{lid}/reset")
    assert ctx.leads.get(lid).status is Status.NEW


def test_unknown_action_404(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    assert client.post(f"/lead/{lid}/explode").status_code == 404
    assert client.post("/lead/999/star").status_code == 404


def test_detail_shows_unreviewed_when_no_stage2(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead(title="Delta role"))
    ctx.scores.save_stage1(lid, 0.7, {"sim": 0.9, "final": 0.7})
    page = client.get(f"/lead/{lid}").text
    assert "Delta role" in page and "unreviewed" in page.lower() and "0.90" in page


def test_detail_shows_stage2(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    ctx.scores.save_stage2(lid, {"verdict": "strong", "fit_summary": "Great fit.", "lead_with_project": "P",
                                 "red_flags": ["night shifts"], "pay_estimate": None})
    page = client.get(f"/lead/{lid}").text
    assert "Great fit." in page and "night shifts" in page


def test_health_page_lists_paused_source(ctx, client):
    for _ in range(3):
        ctx.health.record_failure("remotive", "HTTP 503")
    ctx.health.set_paused("remotive", True)
    page = client.get("/health").text
    assert "remotive" in page and "paused" in page.lower() and "HTTP 503" in page


def test_needs_you_shows_confirmation_link(ctx, client):
    mid = ctx.mail.insert(b"raw", datetime.now(UTC))
    ctx.mail.mark(mid, "confirmation", note="WTTJ confirm", url="https://wttj.example/confirm?t=1")
    page = client.get("/").text
    assert 'href="https://wttj.example/confirm?t=1"' in page
    client.post(f"/needs-you/{mid}/dismiss")
    assert "wttj.example/confirm" not in client.get("/").text


def test_static_htmx_served(client):
    r = client.get("/static/htmx.min.js")
    assert r.status_code == 200 and "htmx" in r.text[:2000]


def toast(r):
    import json
    return json.loads(r.headers["HX-Trigger"])["toast"]


def test_action_sends_toast_with_undo(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    t = toast(client.post(f"/lead/{lid}/dismiss"))
    assert t["msg"] == "Dismissed" and t["undo"].startswith(f"/lead/{lid}/undo?to=new&fb=")
    assert t["target"] == f"#lead-{lid}"


def test_undo_restores_and_removes_feedback(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead(title="Undo me"))
    undo = toast(client.post(f"/lead/{lid}/star"))["undo"]
    r = client.post(undo)
    assert r.status_code == 200 and "Undo me" in r.text
    assert ctx.leads.get(lid).status is Status.NEW and ctx.feedback.count() == 0


def test_undo_twice(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    undo = toast(client.post(f"/lead/{lid}/applied"))["undo"]
    client.post(undo)
    r = client.post(undo)
    assert r.status_code == 200 and ctx.leads.get(lid).status is Status.NEW


def test_undo_other_leads_feedback_untouched(ctx, client, make_lead):
    a = ctx.leads.insert(make_lead(canonical_url="a"))
    b = ctx.leads.insert(make_lead(canonical_url="b"))
    client.post(f"/lead/{a}/star")
    fb_a = toast(client.post(f"/lead/{a}/dismiss"))["undo"].split("fb=")[1]
    client.post(f"/lead/{b}/undo?to=new&fb={fb_a}")
    assert ctx.feedback.count() == 2


def test_undo_rejects_bad_status(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    assert client.post(f"/lead/{lid}/undo?to=bogus&fb=1").status_code == 422


def test_detail_has_actions(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    page = client.get(f"/lead/{lid}").text
    assert f'hx-post="/lead/{lid}/star"' in page and 'id="detail-actions"' in page


def test_detail_action_returns_detail_fragment(ctx, client, make_lead):
    lid = ctx.leads.insert(make_lead())
    r = client.post(f"/lead/{lid}/star", headers={"HX-Target": "detail-actions"})
    assert 'id="detail-actions"' in r.text and 'class="lead ' not in r.text
    assert toast(r)["target"] == "#detail-actions"
