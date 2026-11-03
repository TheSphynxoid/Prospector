import json

import pytest
from fastapi.testclient import TestClient

from prospector.settings_store import load_settings
from prospector.web.app import create_app
from tests.web.conftest import TAILNET

MARKERS = {"LLM_API_KEY": "SECRET-LLM-123", "TELEGRAM_TOKEN": "SECRET-TG-456",
           "BRIDGE_SECRET": "SECRET-BRIDGE-" + "b" * 32, "ADZUNA_APP_KEY": "SECRET-ADZ-789",
           "GITHUB_TOKEN": "SECRET-GH-000"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in {"DATA_DIR": str(tmp_path), "PROFILE_PATH": str(tmp_path / "p.yaml"),
                 "ACCESS_TEAM_DOMAIN": "team.cloudflareaccess.com", "ACCESS_AUD": "aud-tag",
                 "TELEGRAM_CHAT_ID": "42", **MARKERS}.items():
        monkeypatch.setenv(k, v)
    return tmp_path


@pytest.fixture
def setup(env, ctx):
    restarts = []

    def reload():
        ctx.loaded = load_settings(env_file=None)
        ctx.settings = ctx.loaded.settings

    reload()
    ctx.env_file = None
    ctx.restart = lambda: restarts.append(1)
    return TestClient(create_app(ctx), client=TAILNET), restarts, reload


def saved(env):
    p = env / "settings.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def form_of(client):
    """Every field as the page would post it unchanged (secrets empty)."""
    from selectolax.lexbor import LexborHTMLParser
    doc = LexborHTMLParser(client.get("/settings").text)
    data = {}
    for el in doc.css("form#settings-form input, form#settings-form select"):
        name, typ = el.attributes.get("name"), el.attributes.get("type")
        if not name or typ == "submit":
            continue
        if typ == "checkbox":
            if "checked" in el.attributes:
                data.setdefault(name, []).append(el.attributes.get("value") or "1")
            continue
        if el.tag == "select":
            opt = el.css_first("option[selected]") or el.css_first("option")
            data[name] = opt.attributes.get("value", "") if opt else ""
            continue
        data[name] = el.attributes.get("value") or ""
    return data


def test_page_never_renders_secrets(setup):
    client, _, _ = setup
    page = client.get("/settings").text
    assert not [m for m in MARKERS.values() if m in page]
    assert "set — leave empty to keep" in page


def test_unchanged_save_writes_nothing(setup, env):
    client, restarts, _ = setup
    r = client.post("/settings", data=form_of(client))
    assert r.status_code == 200 and "Nothing changed" in r.text
    assert saved(env) is None and restarts == []


def test_save_writes_override_and_restarts(setup, env):
    client, restarts, _ = setup
    data = form_of(client) | {"llm_model": "x-model", "llm_daily_cap": "30"}
    r = client.post("/settings", data=data)
    assert "Restarting" in r.text
    assert saved(env) == {"llm_model": "x-model", "llm_daily_cap": 30}
    assert restarts == [1]


def test_empty_secret_keeps_value(setup, env):
    client, _, reload = setup
    client.post("/settings", data=form_of(client) | {"llm_api_key": "NEW-KEY"})
    reload()
    client.post("/settings", data=form_of(client) | {"llm_model": "y"})
    assert saved(env)["llm_api_key"] == "NEW-KEY"


def test_clear_secret_removes_override(setup, env):
    client, _, reload = setup
    client.post("/settings", data=form_of(client) | {"github_token": "NEW-GH"})
    reload()
    client.post("/settings", data=form_of(client) | {"clear_github_token": "1"})
    assert "github_token" not in saved(env)


def test_bad_number_is_field_error(setup, env):
    client, restarts, _ = setup
    r = client.post("/settings", data=form_of(client) | {"llm_daily_cap": "abc", "stage2_threshold": "2"})
    assert r.status_code == 400
    assert 'id="err-llm_daily_cap"' in r.text and 'id="err-stage2_threshold"' in r.text
    assert 'value="abc"' in r.text  # the posted value is kept for correction
    assert saved(env) is None and restarts == []


def test_unknown_field_ignored(setup, env):
    client, _, _ = setup
    client.post("/settings", data=form_of(client) | {"data_dir": "/etc", "llm_model": "z"})
    assert saved(env) == {"llm_model": "z"}


def test_sources_checkboxes(setup, env):
    client, _, _ = setup
    data = form_of(client)
    data["enabled_sources"] = ["hn", "remotive"]
    client.post("/settings", data=data)
    assert saved(env) == {"enabled_sources": ["hn", "remotive"]}


def test_reset_drops_override(setup, env):
    client, restarts, reload = setup
    client.post("/settings", data=form_of(client) | {"llm_model": "x"})
    reload()
    r = client.post("/settings/reset/llm_model")
    assert "Restarting" in r.text and saved(env) == {} and restarts == [1, 1]


def test_reveal_bridge_secret(setup):
    client, _, _ = setup
    r = client.post("/settings/reveal-bridge-secret")
    assert MARKERS["BRIDGE_SECRET"] in r.text and r.headers["cache-control"] == "no-store"
    assert not [m for k, m in MARKERS.items() if k != "BRIDGE_SECRET" and m in r.text]


def test_origin_shown(setup):
    client, _, reload = setup
    client.post("/settings", data=form_of(client) | {"llm_model": "x"})
    reload()
    page = client.get("/settings").text
    row = page.split('id="f-llm_model"')[1].split('class="field"')[0]
    assert "set here" in row
    assert "from .env" in page.split('id="f-access_aud"')[1].split('class="field"')[0]


def test_rejected_banner(setup, ctx):
    client, _, _ = setup
    ctx.loaded.rejected = "bad json"
    assert "Your saved settings were ignored: bad json" in client.get("/").text


def test_nav_has_settings(setup):
    client, _, _ = setup
    assert 'aria-current="page" href="/settings"' in client.get("/settings").text
