from datetime import UTC, datetime

import httpx
import numpy as np

from prospector.config import Settings
from prospector.context import AppContext
from prospector.models import Kind
from prospector.pipeline import rescore_all
from prospector.profile.model import Profile, Project, Targets
from prospector.rank.embed import lead_text
from prospector.store.db import connect
from tests.rank.test_stage1 import FakeEmbedder

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def make_ctx(tmp_path, profile):
    s = Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p", data_dir=tmp_path)
    return AppContext.create(s, connect(":memory:"), profile, httpx.Client(), embedder=FakeEmbedder())


def seed(ctx, make_lead):
    lead = make_lead(title="hotel room mapping engine in go", body="hotel room mapping engine in go")
    lid = ctx.leads.insert(lead)
    ctx.scores.save_embedding(lid, ctx.embedder.embed([lead_text(lead)], "passage")[0])
    ctx.scores.save_stage1(lid, 0.1, {"final": 0.1})
    ctx.scores.save_stage2(lid, {"verdict": "maybe", "fit_summary": "ok", "lead_with_project": None,
                                 "red_flags": [], "pay_estimate": None})
    return lid


def test_rescore_changes_stage1_keeps_stage2(tmp_path, make_lead):
    prof = Profile(skills={"go": 1}, projects=[Project(name="x", writeup="something unrelated")],
                   targets=Targets(kinds=list(Kind), regions=[]))
    ctx = make_ctx(tmp_path, prof)
    lid = seed(ctx, make_lead)
    assert rescore_all(ctx, NOW) == 1
    row = ctx.leads.get_row(lid)
    assert row.stage1 != 0.1 and row.stage2["verdict"] == "maybe"
    assert ctx.kv.get("rescore_status") == {"state": "done", "count": 1}
    assert ctx.scores.breakdown(lid)["final"] == row.stage1


def test_rescore_with_no_projects(tmp_path, make_lead):
    ctx = make_ctx(tmp_path, Profile(skills={}, projects=[], targets=Targets(kinds=list(Kind), regions=[])))
    seed(ctx, make_lead)
    assert rescore_all(ctx, NOW) == 1


def test_rescore_skips_leads_without_embedding(tmp_path, make_lead):
    ctx = make_ctx(tmp_path, Profile(skills={"go": 1}, projects=[], targets=Targets(kinds=list(Kind), regions=[])))
    ctx.leads.insert(make_lead(canonical_url="no-vec"))
    assert rescore_all(ctx, NOW) == 0


def test_rescore_without_embedder_is_noop(tmp_path, make_lead):
    ctx = make_ctx(tmp_path, Profile(skills={}, projects=[], targets=Targets(kinds=list(Kind), regions=[])))
    seed(ctx, make_lead)
    ctx.embedder = None
    assert rescore_all(ctx, NOW) == 0
    assert np.isfinite(ctx.leads.get_row(1).stage1)
