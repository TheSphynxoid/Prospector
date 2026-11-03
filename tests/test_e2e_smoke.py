import json
from datetime import UTC, datetime

import httpx
import respx
from fastapi.testclient import TestClient

from prospector.config import Settings
from prospector.context import AppContext
from prospector.llm.client import LLMClient
from prospector.models import Kind
from prospector.pipeline import digest_preview, tick
from prospector.profile.model import Profile, Project, Targets
from prospector.store.db import connect
from prospector.web.app import create_app
from tests.rank.test_stage1 import FakeEmbedder
from tests.test_pipeline import ListSource, raw
from tests.web.conftest import TAILNET

GOOD = {"verdict": "strong", "fit_summary": "Fits.", "lead_with_project": "P", "red_flags": [], "pay_estimate": None}


@respx.mock
def test_e2e_smoke(tmp_path):
    respx.post("https://llm.test/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(GOOD)}}]}))
    s = Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p", data_dir=tmp_path, stage2_threshold=0.0)
    prof = Profile(skills={"go": 1}, projects=[Project(name="P", writeup="go services")],
                   targets=Targets(kinds=list(Kind), regions=[]))
    http = httpx.Client()
    ctx = AppContext.create(s, connect(tmp_path / "db.sqlite"), prof, http, embedder=FakeEmbedder(),
                            llm=LLMClient("https://llm.test/v1", "k", "m", http))
    ctx.sources = [ListSource("remotive", [raw("remotive", i) for i in range(3)])]

    now = datetime.now(UTC)
    tick(ctx, now)
    assert len(ctx.leads.list(__import__("prospector.models", fromlist=["Status"]).Status.NEW)) == 3
    assert ctx.scores.top_unreviewed(0.0, 10) == []  # all reviewed by stage 2

    chunks = digest_preview(ctx, now)
    assert chunks and "Go engineer" in chunks[0] and "strong" in chunks[0]

    page = TestClient(create_app(ctx), client=TAILNET).get("/")
    assert page.status_code == 200 and "Go engineer 0" in page.text
