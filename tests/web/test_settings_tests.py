import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from prospector.llm.client import LLMClient
from tests.web.conftest import TAILNET

LLM = "https://llm.test/v1"
KEY = "KEY-XYZ-SECRET"
TG_TOKEN = "TOKEN-TG-SECRET"


@pytest.fixture
def client(app, ctx):
    ctx.http = httpx.Client()
    return TestClient(app, client=TAILNET)


@respx.mock
def test_llm_ok_lists_models(ctx, client):
    ctx.llm = LLMClient(LLM, KEY, "glm-5.3-flash", ctx.http)
    respx.get(f"{LLM}/models").respond(json={"data": [{"id": "glm-5.3-flash"}, {"id": "qwen3.8-flash"}, {"id": "x"}]})
    r = client.post("/settings/test/llm")
    assert "3 models" in r.text and "glm-5.3-flash: available" in r.text and "test-ok" in r.text
    assert '<option value="x">' in r.text  # fills the model suggestions
    assert ctx.kv.get("llm_last_error") is None


@respx.mock
def test_llm_401_reports_without_url(ctx, client):
    ctx.llm = LLMClient(LLM, KEY, "glm-5.3-flash", ctx.http)
    respx.get(f"{LLM}/models").respond(401)
    respx.get("https://opencode.ai/inference/go/v1/models").respond(401)
    r = client.post("/settings/test/llm")
    assert "401" in r.text and "test-err" in r.text
    assert "://" not in r.text and "/v1" not in r.text and KEY not in r.text  # no URL, no key
    assert "401" in ctx.kv.get("llm_last_error")


def test_llm_not_configured(ctx, client):
    ctx.llm = None
    assert "not available" in client.post("/settings/test/llm").text


@respx.mock
def test_telegram_sends_and_hides_token(ctx, client):
    ctx.settings.telegram_token, ctx.settings.telegram_chat_id = SecretStr(TG_TOKEN), "42"
    route = respx.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage").respond(json={"ok": True})
    r = client.post("/settings/test/telegram")
    assert "test-ok" in r.text and json.loads(route.calls[0].request.content)["text"] == "Prospector test message ✓"
    route.respond(401)
    r = client.post("/settings/test/telegram")
    assert "test-err" in r.text and "401" in r.text and TG_TOKEN not in r.text


def test_telegram_not_configured(ctx, client):
    ctx.settings.telegram_token = None
    assert "not set" in client.post("/settings/test/telegram").text.lower()


@respx.mock
def test_email_posts_signed_digest(ctx, client):
    ctx.settings.bridge_url = "https://bridge.test"
    route = respx.post("https://bridge.test/digest").respond(202)
    r = client.post("/settings/test/email")
    assert "test-ok" in r.text
    req = route.calls[0].request
    assert req.headers["X-Prospector-Signature"].startswith("sha256=") and "subject" in json.loads(req.content)


def test_email_not_configured(ctx, client):
    ctx.settings.bridge_url = None
    assert "not set" in client.post("/settings/test/email").text.lower()


def test_run_source_queues(ctx, client):
    class Src:
        id, interval_hours = "hn", 1

        def fetch(self, http):
            return []

    ctx.sources = [Src()]
    queued = []
    ctx.run_background = queued.append
    r = client.post("/settings/test/source/hn")
    assert r.status_code == 200 and "queued" in r.text.lower() and len(queued) == 1
    assert client.post("/settings/test/source/nope").status_code == 404


def test_tests_section_lists_enabled_sources(ctx, client):
    class Src:
        id, interval_hours = "remotive", 1

    ctx.sources = [Src()]
    page = client.get("/settings").text
    assert 'hx-post="/settings/test/source/remotive"' in page and 'hx-post="/settings/test/llm"' in page


@respx.mock
def test_find_chat_id_lists_chats_without_token(ctx, client):
    ctx.settings.telegram_token = SecretStr(TG_TOKEN)
    updates = {"ok": True, "result": [
        {"update_id": 1, "message": {"chat": {"id": 987654321, "type": "private", "first_name": "Hamza"}, "text": "hi"}},
        {"update_id": 2, "message": {"chat": {"id": 987654321, "type": "private", "first_name": "Hamza"}, "text": "again"}},
        {"update_id": 3, "my_chat_member": {"chat": {"id": -100123, "type": "group", "title": "Leads <b>"}}},
    ]}
    respx.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates").respond(json=updates)
    r = client.post("/settings/telegram/find-chat")
    assert "test-ok" in r.text and r.text.count('data-value="987654321"') == 1
    assert 'data-fill="#in-telegram_chat_id"' in r.text and 'data-value="-100123"' in r.text
    assert "Hamza" in r.text and "Leads &lt;b&gt;" in r.text and TG_TOKEN not in r.text


@respx.mock
def test_find_chat_id_no_messages_yet(ctx, client):
    ctx.settings.telegram_token = SecretStr(TG_TOKEN)
    respx.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates").respond(json={"ok": True, "result": []})
    r = client.post("/settings/telegram/find-chat")
    assert "test-err" in r.text and "send your bot a message" in r.text.lower()


@respx.mock
def test_find_chat_id_bad_token(ctx, client):
    ctx.settings.telegram_token = SecretStr(TG_TOKEN)
    respx.get(f"https://api.telegram.org/bot{TG_TOKEN}/getUpdates").respond(401)
    r = client.post("/settings/telegram/find-chat")
    assert "test-err" in r.text and "401" in r.text and TG_TOKEN not in r.text


def test_find_chat_id_needs_token(ctx, client):
    ctx.settings.telegram_token = None
    assert "token" in client.post("/settings/telegram/find-chat").text.lower()


def test_settings_page_has_find_chat_button(client):
    page = client.get("/settings").text
    assert 'hx-post="/settings/telegram/find-chat"' in page


def test_adzuna_not_enabled_by_default():
    from prospector.config import Settings
    assert "adzuna" not in Settings.model_fields["enabled_sources"].default
