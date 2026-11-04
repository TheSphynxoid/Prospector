from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from prospector.config import Settings
from prospector.store.db import connect
from prospector.store.kv import KV
from prospector.web.checklist import setup_items
from tests.web.conftest import TAILNET

EXAMPLE = Path(__file__).resolve().parents[2] / "profile.example.yaml"


@pytest.fixture
def fresh(tmp_path):
    prof = tmp_path / "profile.yaml"
    prof.write_bytes(EXAMPLE.read_bytes())
    s = Settings(_env_file=None, llm_api_key="REPLACE_ME", bridge_secret="x" * 32, profile_path=prof,
                 access_team_domain="REPLACE_ME.cloudflareaccess.com", access_aud="REPLACE_ME", data_dir=tmp_path)
    return s, KV(connect(":memory:"))


def hrefs(s, kv):
    return [i.href for i in setup_items(s, kv, s.profile_path, EXAMPLE)]


def test_all_open_on_fresh_install(fresh):
    assert hrefs(*fresh) == ["/settings/connections#f-llm_api_key", "/settings/connections#f-telegram_token", "/settings/connections#f-bridge_url",
                             "/settings/connections#f-access_team_domain", "/settings/profile"]


def test_all_done(fresh):
    s, kv = fresh
    s.llm_api_key, s.telegram_token, s.telegram_chat_id = SecretStr("real"), SecretStr("t"), "1"
    s.bridge_url, s.access_team_domain, s.access_aud = "https://b", "team.cloudflareaccess.com", "aud"
    s.profile_path.write_text(EXAMPLE.read_text(encoding="utf-8") + "\n# mine\n", encoding="utf-8")
    assert hrefs(s, kv) == []


@pytest.mark.parametrize("err, flagged", [("could not list models (HTTP 401 from opencode.ai)", True),
                                          ("HTTP 403 from opencode.ai", True), ("timeout", False), (None, False)])
def test_rejected_key_flagged(fresh, err, flagged):
    s, kv = fresh
    s.llm_api_key = SecretStr("real")
    kv.set("llm_last_error", err)
    assert ("/settings/connections#f-llm_api_key" in hrefs(s, kv)) is flagged


def test_missing_example_skips_profile_item(fresh, tmp_path):
    s, kv = fresh
    assert "/settings/profile" not in [i.href for i in setup_items(s, kv, s.profile_path, tmp_path / "missing.yaml")]


def test_overview_shows_and_hides_card(ctx, app):
    client = TestClient(app, client=TAILNET)
    ctx.settings.llm_api_key = SecretStr("REPLACE_ME")
    page = client.get("/").text
    assert 'id="setup"' in page and 'href="/settings/connections#f-llm_api_key"' in page
    ctx.settings.llm_api_key, ctx.settings.telegram_token, ctx.settings.telegram_chat_id = \
        SecretStr("k"), SecretStr("t"), "1"
    ctx.settings.bridge_url = "https://b"
    assert 'id="setup"' not in client.get("/").text  # conftest access values and missing profile file pass
