import json

import httpx
import pytest
import respx

from prospector.llm.client import LLMClient, LLMError

BASE = "https://llm.test/v1"


def reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


@pytest.fixture
def client():
    with httpx.Client() as http:
        yield LLMClient(BASE, "key", "m", http)


@respx.mock
def test_chat_sends_system_then_history(client):
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=reply("ok"))
    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
               {"role": "user", "content": "c"}]
    assert client.chat("S", history, "sid") == "ok"
    body = json.loads(route.calls.last.request.content)
    assert body["messages"] == [{"role": "system", "content": "S"}, *history]
    assert body["temperature"] == 0.4
    assert client.answered == 1


@respx.mock
def test_complete_still_temperature_zero(client):
    route = respx.post(f"{BASE}/chat/completions").mock(return_value=reply("ok"))
    client.complete("S", "u", "sid")
    body = json.loads(route.calls.last.request.content)
    assert body["temperature"] == 0 and len(body["messages"]) == 2


@respx.mock
def test_chat_maps_errors(client):
    respx.post(f"{BASE}/chat/completions").mock(return_value=httpx.Response(500))
    with pytest.raises(LLMError):
        client.chat("S", [{"role": "user", "content": "u"}], "sid")
    assert client.answered == 0
