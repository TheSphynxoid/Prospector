"""Final-review fixes for the settings/profile branch."""
from datetime import UTC, datetime

import pytest

from prospector.assist import drafts
from prospector.profile.model import Profile
from tests.web.test_settings_page import (as_form, env, example_profile, form_of, profile_form_of,  # noqa: F401
                                          saved, setup)


@pytest.mark.parametrize("field,value", [("bridge_secret", "n" * 40), ("dashboard_url", "https://new.example.net")])
def test_startup_bound_fields_restart(setup, field, value):
    client, restarts, _ = setup
    client.post("/settings", data=form_of(client, ("/settings/connections",)) | {field: value})
    assert restarts == [1]


def test_legacy_boost_weights_clamped():
    p = Profile(skills={}, projects=[], targets={"kinds": ["job"], "regions": []},
                boost_keywords={"python": 1.5, "rust": -3, "zero": 0, "x" * 100: 0.5})
    got = {i.phrase: i.weight for i in p.interests}
    assert got["python"] == 1.0 and got["rust"] == -1.0 and "zero" not in got and "x" * 80 in got


def _fake_embedder():
    from tests.rank.test_stage1 import FakeEmbedder
    return FakeEmbedder()


def test_stale_running_state_does_not_block(example_profile, ctx):
    client, _, _ = example_profile
    queued = []
    ctx.embedder, ctx.run_background = _fake_embedder(), queued.append
    ctx.kv.set("rescore_status", {"state": "running", "count": 5})  # left over from a killed process
    client.post("/settings/profile", data=as_form(profile_form_of(client)))
    assert len(queued) == 1
    frag = client.get("/settings/rescore-status").text
    assert "every 2s" in frag  # this run is real, so it polls


def test_stale_running_state_stops_polling(example_profile, ctx):
    client, _, _ = example_profile
    ctx.kv.set("rescore_status", {"state": "running", "count": 5})
    assert "every 2s" not in client.get("/settings/rescore-status").text


def test_rescore_error_clears_running(ctx, monkeypatch):
    from prospector import pipeline
    ctx.embedder = _fake_embedder()
    monkeypatch.setattr(pipeline, "profile_vectors", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        pipeline.rescore_all(ctx, datetime.now(UTC))
    assert ctx.kv.get("rescore_status")["state"] == "error" and not ctx.rescoring


def test_save_during_rescore_runs_again(example_profile, ctx):
    from prospector.web.settings.pages import reload_profile
    queued = []
    ctx.embedder, ctx.run_background = _fake_embedder(), queued.append
    ctx.rescoring = True
    assert reload_profile(ctx, ctx.profile) is False and queued == [] and ctx.rescore_again


def test_rescore_keeps_count(ctx, make_lead, monkeypatch):
    import numpy as np

    from prospector import pipeline
    ctx.embedder = _fake_embedder()
    for i in range(2):
        lid = ctx.leads.insert(make_lead(canonical_url=f"k{i}"))
        ctx.scores.save_embedding(lid, np.ones(64, dtype=np.float32) / 8)
    seen = []
    real = ctx.kv.set
    monkeypatch.setattr(ctx.kv, "set", lambda k, v: (seen.append(v) if k == "rescore_status" else None, real(k, v)))
    pipeline.rescore_all(ctx, datetime.now(UTC))
    assert seen[0] == {"state": "running", "count": 2} and seen[-1] == {"state": "done", "count": 2}


def test_checklist_links_point_at_pages(tmp_path):
    from prospector.config import Settings
    from prospector.store.db import connect
    from prospector.store.kv import KV
    from prospector.web.checklist import setup_items
    s = Settings(_env_file=None, llm_api_key="CHANGE_ME", bridge_secret="s", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p", data_dir=tmp_path)
    example = tmp_path / "ex"
    example.write_text("x"), (tmp_path / "p").write_text("x")
    hrefs = [i.href for i in setup_items(s, KV(connect(":memory:")), tmp_path / "p", example)]
    assert "/settings/connections#f-telegram_token" in hrefs and "/settings/profile" in hrefs
    assert not any(h.startswith("/settings#") for h in hrefs)


def test_interest_weight_accepts_any_step(example_profile):
    client, _, _ = example_profile
    page = client.get("/settings/profile").text
    row = page.split('name="boost[0][weight]"')[1].split(">")[0]
    assert 'step="any"' in row


def test_row_inputs_add_on_enter(example_profile):
    client, _, _ = example_profile
    page = client.get("/settings/profile").text
    assert 'name="skills[0][name]"' in page and 'data-enter-adds-row' in page.split('name="skills[0][name]"')[1].split(">")[0]


@pytest.mark.parametrize("text,expected", [
    ("Here:\n<<<DRAFT Hi, I'm Hamza. DRAFT>>>", [("text", "Here:"), ("draft", "Hi, I'm Hamza.")]),
    ("<<<DRAFT\nHi\nRegards DRAFT>>>", [("draft", "Hi\nRegards")]),
    ("stray DRAFT>>> marker", [("text", "stray marker")]),
])
def test_drafts_inline_markers(text, expected):
    assert drafts.split(text) == expected
