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
                 "TELEGRAM_CHAT_ID": "42", "ALLOWED_HOSTS": '["testserver"]', **MARKERS}.items():
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


def profile_form_of(client):
    from selectolax.lexbor import LexborHTMLParser
    doc = LexborHTMLParser(client.get("/settings").text)
    pairs = []
    for el in doc.css("form#profile-form input, form#profile-form textarea, form#profile-form select"):
        name, typ = el.attributes.get("name"), el.attributes.get("type")
        if not name:
            continue
        if typ == "checkbox":
            if "checked" in el.attributes:
                pairs.append((name, el.attributes.get("value") or "1"))
        elif el.tag == "textarea":
            pairs.append((name, el.text()))
        elif el.tag == "select":
            opt = el.css_first("option[selected]") or el.css_first("option")
            pairs.append((name, opt.attributes.get("value", "") if opt else ""))
        else:
            pairs.append((name, el.attributes.get("value") or ""))
    return pairs


def as_form(pairs):
    """httpx treats a list as raw bytes; a dict of lists posts repeated fields."""
    out = {}
    for k, v in pairs:
        out.setdefault(k, []).append(v)
    return out


@pytest.fixture
def example_profile(setup, ctx, env):
    from pathlib import Path

    from prospector.profile.model import load_profile
    src = Path(__file__).resolve().parents[2] / "profile.example.yaml"
    ctx.settings.profile_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    ctx.profile = load_profile(ctx.settings.profile_path)
    return setup


def test_profile_page_round_trip_saves_and_restarts(example_profile, ctx):
    from prospector.profile.model import load_profile
    client, restarts, _ = example_profile
    before = ctx.profile
    r = client.post("/settings/profile", data=as_form(profile_form_of(client)))
    assert "Restarting" in r.text and restarts == [1]
    assert load_profile(ctx.settings.profile_path) == before
    assert ctx.settings.profile_path.with_name("profile.yaml.bak").exists() or \
        ctx.settings.profile_path.with_suffix(ctx.settings.profile_path.suffix + ".bak").exists()


def test_profile_post_invalid_400_keeps_edits(example_profile, ctx):
    client, restarts, _ = example_profile
    pairs = [(k, "9" if k == "skills[0][weight]" else ("EDITED WRITEUP" if k == "projects[0][writeup]" else v))
             for k, v in profile_form_of(client)]
    r = client.post("/settings/profile", data=as_form(pairs))
    assert r.status_code == 400 and restarts == []
    assert "EDITED WRITEUP" in r.text and 'id="profile-error"' in r.text


def test_rescore_button_queues(example_profile, ctx):
    client, _, _ = example_profile
    from tests.rank.test_stage1 import FakeEmbedder
    queued = []
    ctx.embedder = FakeEmbedder()
    ctx.run_background = queued.append
    r = client.post("/settings/rescore")
    assert r.status_code == 200 and len(queued) == 1 and "Re-scoring" in r.text


def test_untouched_save_with_empty_env_optionals(setup, env, monkeypatch):
    client, restarts, reload = setup
    for k in ("TELEGRAM_CHAT_ID", "BRIDGE_URL", "ADZUNA_APP_ID"):
        monkeypatch.setenv(k, "")  # compose passes empty .env entries as ""
    reload()
    r = client.post("/settings", data=form_of(client))
    assert "Nothing changed" in r.text and saved(env) is None and restarts == []


def test_foreign_host_refused(setup):
    client, _, _ = setup
    assert client.get("/settings", headers={"Host": "evil.example:8080"}).status_code == 400
    assert client.post("/settings/reveal-bridge-secret",
                       headers={"Host": "evil.example", "Origin": "http://evil.example"}).status_code == 400
    assert client.get("/healthz", headers={"Host": "127.0.0.1:8080"}).status_code == 200


def test_blank_tnd_rate_saves_as_none(setup, env):
    client, restarts, reload = setup
    data = form_of(client) | {"usd_tnd_rate": "3.2"}
    client.post("/settings", data=data)
    assert saved(env)["usd_tnd_rate"] == 3.2
    reload()
    data = form_of(client) | {"usd_tnd_rate": ""}
    client.post("/settings", data=data)
    assert saved(env).get("usd_tnd_rate") is None
    assert "Blank uses today" in client.get("/settings").text


def test_settings_shows_today_rates(setup, ctx):
    from prospector import fx
    client, _, _ = setup
    assert "No rates fetched yet" in client.get("/settings").text
    for code, v in (("TND", 3.004), ("EUR", 0.893), ("GBP", 0.79)):
        ctx.conn.execute("INSERT INTO fx_rates VALUES (?,?,?,?)", (fx.today().isoformat(), code, v, "open.er-api.com"))
    page = client.get("/settings").text
    assert "1 USD = 3.004 TND · 0.893 EUR · 0.79 GBP" in page and "open.er-api.com" in page
    assert "out of date" not in page


def test_settings_has_followup_days(setup):
    client, _, _ = setup
    assert 'name="followup_days"' in client.get("/settings").text
