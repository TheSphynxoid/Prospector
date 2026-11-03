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
