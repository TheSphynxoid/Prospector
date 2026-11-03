import pytest
from pydantic import ValidationError
from starlette.datastructures import FormData

from prospector.config import Settings
from prospector.models import Kind
from prospector.profile.form import profile_from_rows, rows_from_form, rows_from_profile
from prospector.profile.model import Pricing, Profile, Targets


def base_profile(**kw):
    return Profile(skills={}, projects=[], targets=Targets(kinds=list(Kind), regions=[]), **kw)


def test_pricing_defaults():
    assert base_profile().pricing == Pricing(rate=25, floor=15, hours_per_day=6)


@pytest.mark.parametrize("kw", [dict(rate=25, floor=30), dict(rate=0, floor=0), dict(rate=25, floor=0),
                                dict(hours_per_day=0), dict(hours_per_day=13)])
def test_pricing_validation(kw):
    with pytest.raises(ValidationError):
        Pricing(**kw)


def test_form_round_trip_pricing():
    form = FormData([("kinds", "job"), ("pricing[rate]", "30"), ("pricing[floor]", "18"),
                     ("pricing[hours_per_day]", "5")])
    p = profile_from_rows(rows_from_form(form))
    assert p.pricing == Pricing(rate=30, floor=18, hours_per_day=5)
    assert profile_from_rows(rows_from_profile(p)).pricing == p.pricing


def test_form_without_pricing_uses_defaults():
    assert profile_from_rows(rows_from_form(FormData([("kinds", "job")]))).pricing == Pricing()


def test_form_bad_pricing_rejected():
    with pytest.raises((ValidationError, ValueError)):
        profile_from_rows(rows_from_form(FormData([("kinds", "job"), ("pricing[rate]", "abc")])))


def settings(**kw):
    return Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a",
                    profile_path="p", **kw)


def test_assistant_settings_defaults_and_bounds():
    s = settings()
    assert (s.assistant_daily_cap, s.assistant_model, s.usd_tnd_rate) == (100, None, 3.0)
    for bad in (dict(assistant_daily_cap=0), dict(assistant_daily_cap=2001), dict(usd_tnd_rate=0)):
        with pytest.raises(ValidationError):
            settings(**bad)


@pytest.mark.parametrize("model, expected", [("big", "big"), (None, "glm-5.3-flash")])
def test_build_context_assistant_client(tmp_path, model, expected):
    from prospector.__main__ import build_context
    prof = tmp_path / "p.yaml"
    prof.write_text("skills: {}\nprojects: []\ntargets: {kinds: [job], regions: []}\n", encoding="utf-8")
    s = Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a",
                 profile_path=prof, data_dir=tmp_path, assistant_model=model)
    ctx = build_context(s, with_embedder=False, with_sources=False)
    assert ctx.assistant_llm.model == expected
