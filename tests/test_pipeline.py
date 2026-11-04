from datetime import UTC, datetime

import httpx
import pytest
import respx

from prospector.config import Settings
from prospector.context import AppContext
from prospector.llm.client import LLMClient
from prospector.models import Kind, RawLead, Status
from prospector.pipeline import ingest, nightly, select_model
from prospector.profile.model import Filters, Profile, Project, Targets
from prospector.store.db import connect
from tests.rank.test_stage1 import FakeEmbedder

NOW = datetime(2026, 11, 3, 12, tzinfo=UTC)


class ListSource:
    interval_hours = 1

    def __init__(self, sid, leads):
        self.id, self.leads = sid, leads

    def fetch(self, http):
        return self.leads


def raw(sid, i, **kw):
    base = dict(source_id=sid, external_id=str(i), url=f"https://{sid}.test/{i}", title=f"Go engineer {i}",
                body="Build Go services", company=f"Co{i}")
    base.update(kw)
    return RawLead(**base)


@pytest.fixture
def ctx(tmp_path):
    s = Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p", data_dir=tmp_path)
    prof = Profile(skills={"go": 1}, projects=[Project(name="P", writeup="go services")],
                   targets=Targets(kinds=list(Kind), regions=[]), filters=Filters(blocked_keywords=["php"]))
    return AppContext.create(s, connect(tmp_path / "db.sqlite"), prof, httpx.Client(), embedder=FakeEmbedder())


def test_ingest_new_merged_filtered(ctx):
    existing = raw("himalayas", 1, title="Senior Go Engineer", company="Acme")
    ingest(ctx, ListSource("himalayas", [existing]), NOW)
    src = ListSource("remotive", [
        raw("remotive", 2, title="Rust dev"),
        raw("remotive", 3, title="Senior Go Engineer (Remote)", company="ACME Inc."),
        raw("remotive", 4, title="PHP developer"),
    ])
    stats = ingest(ctx, src, NOW)
    assert (stats.fetched, stats.new, stats.merged, stats.filtered) == (3, 1, 1, 1)
    acme = ctx.leads.recent_by_company("acme")[0]
    assert acme.sources == ["himalayas", "remotive"]
    php = ctx.leads.by_canonical_url("https://remotive.test/4")
    assert php.status is Status.FILTERED and php.filter_reason == "blocked keyword: php"
    rust = ctx.leads.by_canonical_url("https://remotive.test/2")
    assert ctx.scores.breakdown(rust.id)["final"] >= 0
    assert ctx.scores.embeddings([rust.id]).shape == (1, FakeEmbedder.dim)


def test_ingest_failing_source_counts_nothing(ctx):
    class Boom:
        id, interval_hours = "boom", 1

        def fetch(self, http):
            raise RuntimeError("down")
    stats = ingest(ctx, Boom(), NOW)
    assert stats.fetched == 0 and ctx.health.get("boom").consecutive_failures == 1


def test_nightly_backup_and_retention(ctx, tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    for d in range(1, 17):
        (backups / f"prospector-202610{d:02d}.db").write_bytes(b"old")
    nightly(ctx, NOW)
    files = sorted(p.name for p in backups.iterdir())
    assert len(files) == 14 and "prospector-20261103.db" in files
    assert "prospector-20261001.db" not in files


def test_nightly_reweights_from_feedback(ctx):
    for i in range(12):
        lid = ctx.leads.insert(ctx_lead(i))
        ctx.scores.save_stage1(lid, 0.5, {"sim": 1.0 if i < 6 else 0.0, "keywords": 0.5, "pay": 0.5,
                                          "remote": 0.5, "freshness": 0.5, "feedback": 0.5, "final": 0.5})
        ctx.feedback.record(lid, "star" if i < 6 else "dismiss")
    nightly(ctx, NOW)
    assert ctx.kv.get("weights")["sim"] > 0.40


def ctx_lead(i):
    from prospector.normalize.normalize import normalize
    return normalize(raw("x", 100 + i))


@respx.mock
def test_select_model_falls_back():
    with httpx.Client() as http:
        client = LLMClient("https://llm.test/v1", "k", "glm-5.3-flash", http)
        respx.get("https://llm.test/v1/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "qwen3.8-flash"}]}))
        assert select_model(client, "glm-5.3-flash", "qwen3.8-flash") == "qwen3.8-flash"
        respx.get("https://llm.test/v1/models").mock(return_value=httpx.Response(200, json={"data": [{"id": "x"}]}))
        assert select_model(client, "glm-5.3-flash", "qwen3.8-flash") is None
        respx.get("https://llm.test/v1/models").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "glm-5.3-flash"}]}))
        assert select_model(client, "glm-5.3-flash", "qwen3.8-flash") == "glm-5.3-flash"


def test_ingest_saves_and_refreshes_bids(ctx):
    ingest(ctx, ListSource("freelancer", [raw("freelancer", 1, bid_count=5)]), NOW)
    lead = ctx.leads.by_canonical_url("https://freelancer.test/1")
    assert ctx.signals.bids(lead.id) == 5
    ctx.conn.execute("UPDATE scores SET scored_at = '2000-01-01' WHERE lead_id = ?", (lead.id,))
    ingest(ctx, ListSource("freelancer", [raw("freelancer", 1, bid_count=40)]), NOW)
    assert ctx.signals.bids(lead.id) == 40
    scored = ctx.conn.execute("SELECT scored_at FROM scores WHERE lead_id = ?", (lead.id,)).fetchone()[0]
    assert scored != "2000-01-01"  # the new count re-scored the lead


def test_ingest_without_bids_leaves_signals_empty(ctx):
    ingest(ctx, ListSource("remotive", [raw("remotive", 1)]), NOW)
    assert ctx.signals.bids(ctx.leads.by_canonical_url("https://remotive.test/1").id) is None
