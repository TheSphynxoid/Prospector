import pytest

from prospector.profile.model import About, Interest, Profile
from prospector.profile.yaml_io import ProfileYamlError, dump, load

P = Profile(skills={"go": 1.0, "c++": 0.7}, projects=[{"name": "Room mapping", "writeup": "Hotel rooms.", "tags": ["go"]}],
            targets={"kinds": ["job", "gig"], "regions": ["EU"]}, interests=[Interest(phrase="rust", weight=-0.5)],
            about=About(name="Hamza", headline="Engineer"))


def test_yaml_round_trip():
    assert load(dump(P)) == P


def test_yaml_syntax_error_has_line():
    text = "skills:\n  go: 1\nprojects: []\n  bad: indent\ntargets: {kinds: [job], regions: []}\n"
    with pytest.raises(ProfileYamlError) as e:
        load(text)
    assert e.value.line == 4


def test_yaml_validation_error_points_at_key():
    text = dump(P).replace("weight: -0.5", "weight: 7")
    with pytest.raises(ProfileYamlError) as e:
        load(text)
    line = text.splitlines()[e.value.line - 1]
    assert "weight" in line and "interests" in e.value.message


def test_yaml_not_a_mapping():
    with pytest.raises(ProfileYamlError):
        load("- just\n- a list\n")
