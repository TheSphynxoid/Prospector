import httpx
import pytest
import respx

from prospector.store import conn_status
from tests.web.test_settings_page import env, form_of, saved, setup  # noqa: F401  (fixtures)

H = "http://h:8081"


@pytest.fixture
def client(setup, ctx):
    ctx.http = httpx.Client()
    return setup[0]


def card(page, name):
    return page.split(f'id="card-{name}"')[1].split('class="card conn-card')[0]


@respx.mock
def test_search_card_and_test_route(client, ctx):
    page = client.get("/settings/connections").text
    assert "Web search" in page and "Not set" in card(page, "search")
    ctx.settings.searxng_url = H
    respx.get(f"{H}/search").respond(json={"results": []})
    r = client.post("/settings/test/search")
    assert "test-ok" in r.text
    assert conn_status.get(ctx.kv, "search")["ok"] is True
    assert "Connected" in card(client.get("/settings/connections").text, "search")
    respx.get(f"{H}/search").respond(500)
    r = client.post("/settings/test/search")
    assert "test-err" in r.text and conn_status.get(ctx.kv, "search")["ok"] is False


def test_searxng_url_validated(tmp_path):
    from prospector.config import EDITABLE, Settings
    assert "searxng_url" in EDITABLE
    with pytest.raises(ValueError):
        Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p", data_dir=tmp_path, searxng_url="ftp://x")
