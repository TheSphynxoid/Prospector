import httpx
import pytest
import respx
from pydantic import SecretStr

from prospector.store import conn_status
from tests.web.test_settings_page import env, form_of, saved, setup  # noqa: F401  (fixtures)

TG = "TOKEN-TG-SECRET"


@pytest.fixture
def client(setup, ctx):
    ctx.http = httpx.Client()
    return setup[0]


def card(page, name):
    return page.split(f'id="card-{name}"')[1].split('class="card conn-card')[0]


def test_cards_show_states(client, ctx):
    ctx.settings.telegram_token = None
    page = client.get("/settings/connections").text
    assert "Not set" in card(page, "telegram")
    ctx.settings.telegram_token, ctx.settings.telegram_chat_id = SecretStr(TG), "42"
    conn_status.record(ctx.kv, "telegram", True)
    conn_status.record(ctx.kv, "llm", False, "HTTP 401 from the LLM")
    page = client.get("/settings/connections").text
    assert "Connected" in card(page, "telegram")
    assert "Failing" in card(page, "llm") and "HTTP 401 from the LLM" in card(page, "llm")
    assert TG not in page


@respx.mock
def test_test_button_records_status(client, ctx):
    ctx.settings.telegram_token, ctx.settings.telegram_chat_id = SecretStr(TG), "42"
    respx.post(f"https://api.telegram.org/bot{TG}/sendMessage").respond(401)
    client.post("/settings/test/telegram")
    assert conn_status.get(ctx.kv, "telegram")["ok"] is False
    respx.post(f"https://api.telegram.org/bot{TG}/sendMessage").respond(json={"ok": True})
    client.post("/settings/test/telegram")
    assert conn_status.get(ctx.kv, "telegram")["ok"] is True


@respx.mock
def test_digest_send_records_status(ctx):
    from prospector.notify.run import send_digest
    from datetime import UTC, datetime
    ctx.http = httpx.Client()
    ctx.settings.telegram_token, ctx.settings.telegram_chat_id = SecretStr(TG), "42"
    ctx.settings.bridge_url = None
    respx.post(f"https://api.telegram.org/bot{TG}/sendMessage").respond(json={"ok": True})
    send_digest(ctx, datetime.now(UTC))
    assert conn_status.get(ctx.kv, "telegram")["ok"] is True


def test_find_chat_in_telegram_card(client):
    assert 'hx-post="/settings/telegram/find-chat"' in card(client.get("/settings/connections").text, "telegram")


def test_llm_record_keeps_checklist_key(ctx):
    conn_status.record(ctx.kv, "llm", False, "401")
    assert ctx.kv.get("llm_last_error") == "401"
    conn_status.record(ctx.kv, "llm", True)
    assert ctx.kv.get("llm_last_error") is None


def test_connections_save_still_works(client, env):
    data = form_of(client, ("/settings/connections",)) | {"dashboard_url": "https://p.example.net"}
    r = client.post("/settings", data=data, follow_redirects=True)
    assert saved(env)["dashboard_url"] == "https://p.example.net" and "Saved." in r.text
