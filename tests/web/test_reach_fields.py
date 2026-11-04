import pytest
from pydantic import ValidationError

from prospector.models import Kind
from prospector.profile.model import Profile, Targets
from tests.web.test_settings_page import (as_form, env, example_profile, profile_form_of,  # noqa: F401
                                          setup)


def test_targets_defaults():
    t = Targets(kinds=[Kind.JOB], regions=[])
    assert t.levels == ["intern", "junior", "mid", "senior", "lead"]
    assert t.work_from == ["worldwide", "anywhere", "emea", "africa", "mena", "tunisia", "france"]


def test_work_from_normalised_and_levels_required():
    t = Targets(kinds=[Kind.JOB], regions=[], work_from=["  EMEA ", "Tunisia", ""])
    assert t.work_from == ["emea", "tunisia"]
    with pytest.raises(ValidationError, match="Pick at least one level"):
        Targets(kinds=[Kind.JOB], regions=[], levels=[])


def test_pfe_profile_gains_internship():
    p = Profile.model_validate({"skills": {}, "projects": [], "targets": {"kinds": ["job", "pfe"], "regions": []}})
    assert Kind.INTERNSHIP in p.targets.kinds
    q = Profile.model_validate({"skills": {}, "projects": [], "targets": {"kinds": ["job"], "regions": []}})
    assert Kind.INTERNSHIP not in q.targets.kinds


def test_profile_form_round_trip_levels(example_profile, ctx):
    client, _, _ = example_profile
    pairs = [p for p in profile_form_of(client) if p[0] not in ("levels", "work_from")]
    pairs += [("levels", "intern"), ("levels", "junior"), ("work_from", "EMEA, Tunisia")]
    r = client.post("/settings/profile", data=as_form(pairs))
    assert r.status_code == 200
    assert ctx.profile.targets.levels == ["intern", "junior"] and ctx.profile.targets.work_from == ["emea", "tunisia"]
    page = client.get("/settings/profile").text
    assert 'name="levels" value="intern" checked' in page and 'name="levels" value="mid" >' in page


def test_profile_form_no_level_is_an_error(example_profile, ctx):
    client, _, _ = example_profile
    pairs = [p for p in profile_form_of(client) if p[0] != "levels"]
    r = client.post("/settings/profile", data=as_form(pairs))
    assert r.status_code == 400 and "Pick at least one level" in r.text
