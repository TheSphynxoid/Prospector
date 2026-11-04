import pytest

from prospector.profile.model import load_profile
from tests.web.test_settings_page import env, form_of, saved, setup  # noqa: F401  (fixtures)


@pytest.fixture
def client(setup):
    return setup[0]


@pytest.fixture
def restarts(setup):
    return setup[1]


def test_hub_lists_areas(client):
    page = client.get("/settings").text
    for key in ("connections", "sources", "ai", "profile", "pricing", "schedule"):
        assert f'href="/settings/{key}"' in page
    assert "of 5 set up" in page


def test_unknown_area_404(client):
    assert client.get("/settings/nope").status_code == 404


def test_live_field_does_not_restart(client, ctx, restarts, env):
    r = client.post("/settings", data=form_of(client, ("/settings/ai",)) | {"llm_daily_cap": "40"},
                    follow_redirects=True)
    assert restarts == [] and ctx.settings.llm_daily_cap == 40 and "Saved." in r.text
    assert saved(env)["llm_daily_cap"] == 40


def test_cold_field_restarts(client, restarts):
    r = client.post("/settings", data=form_of(client, ("/settings/ai",)) | {"llm_model": "x-model"})
    assert restarts == [1] and "Restarting" in r.text


def test_tnd_override_applies_live(client, ctx, restarts):
    data = form_of(client, ("/settings/pricing",))
    r = client.post("/settings/pricing", data=_pricing(data) | {"usd_tnd_rate": "3.2"}, follow_redirects=True)
    assert restarts == [] and ctx.fx.rate("TND") == 3.2 and "override of 3.2 TND is in use" in r.text


def _pricing(data):
    return {"rate": "25", "floor": "15", "hours_per_day": "6"} | {k: v for k, v in data.items() if k != "_area"}


def test_pricing_saves_profile_pricing(client, ctx, restarts):
    ctx.settings.profile_path.write_text("skills: {}\nprojects: []\ntargets: {kinds: [job], regions: []}\n",
                                         encoding="utf-8")
    r = client.post("/settings/pricing", data={"rate": "30", "floor": "18", "hours_per_day": "5", "usd_tnd_rate": ""},
                    follow_redirects=True)
    assert r.status_code == 200 and restarts == []
    assert ctx.profile.pricing.rate == 30 and load_profile(ctx.settings.profile_path).pricing.floor == 18


def test_pricing_floor_above_rate_error(client, ctx):
    before = ctx.profile.pricing
    r = client.post("/settings/pricing", data={"rate": "10", "floor": "20", "hours_per_day": "6", "usd_tnd_rate": ""})
    assert r.status_code == 400 and 'class="field-err"' in r.text and ctx.profile.pricing == before


def test_cold_inputs_marked(client):
    page = client.get("/settings/ai").text
    assert 'name="llm_model" data-cold' in page and 'name="llm_daily_cap" data-cold' not in page
