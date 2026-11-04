import pytest

from tests.web.test_settings_page import env, form_of, saved, setup  # noqa: F401  (fixtures)


@pytest.fixture
def client(setup):
    return setup[0]


def test_sources_rows_and_toggle(setup, ctx, env):
    client, restarts, _ = setup
    ctx.health.record_failure("remotive", "HTTP 503")
    page = client.get("/settings/sources").text
    assert 'id="src-remotive"' in page and "HTTP 503" in page and 'id="src-hn"' in page
    data = form_of(client, ("/settings/sources",))
    data["enabled_sources"] = [s for s in data["enabled_sources"] if s != "remotive"]
    client.post("/settings", data=data)
    assert restarts == [1] and "remotive" not in saved(env)["enabled_sources"]


def test_run_now_only_for_running_sources(client, ctx):
    class Src:
        id, interval_hours = "remotive", 1
    ctx.sources = [Src()]
    page = client.get("/settings/sources").text
    assert 'hx-post="/settings/test/source/remotive"' in page
    assert 'hx-post="/settings/test/source/hn"' not in page


def test_health_redirects(client):
    r = client.get("/health", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/settings/sources"


def test_nav_sources_link(client):
    assert 'href="/settings/sources"' in client.get("/").text
