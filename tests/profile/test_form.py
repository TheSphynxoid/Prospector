from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from starlette.datastructures import FormData

from prospector.profile.form import profile_from_rows, rows_from_form, rows_from_profile, save_profile
from prospector.profile.model import load_profile

ROOT = Path(__file__).resolve().parents[2]


def test_rows_round_trip_example():
    p = load_profile(ROOT / "profile.example.yaml")
    assert profile_from_rows(rows_from_profile(p)) == p


def test_form_parsing_drops_empty_rows():
    form = FormData([
        ("skills[0][name]", "go"), ("skills[0][weight]", "1"),
        ("skills[1][name]", ""), ("skills[1][weight]", "0.5"),
        ("projects[0][name]", "P"), ("projects[0][writeup]", "w"), ("projects[0][tags]", "a, b,"),
        ("projects[1][name]", ""), ("projects[1][writeup]", ""), ("projects[1][tags]", ""),
        ("kinds", "job"), ("kinds", "bounty"), ("regions", "tunisia, eu"),
        ("min_pay[0][currency]", "USD"), ("min_pay[0][period]", "year"), ("min_pay[0][amount]", "30000"),
        ("min_pay[1][currency]", ""), ("min_pay[1][period]", "year"), ("min_pay[1][amount]", ""),
        ("languages", "en,fr"), ("blocked_keywords", ""), ("blocked_companies", "Evil Corp"),
        ("boost[0][keyword]", "golang"), ("boost[0][weight]", "1"),
    ])
    p = profile_from_rows(rows_from_form(form))
    assert p.skills == {"go": 1.0}
    assert [(x.name, x.tags) for x in p.projects] == [("P", ["a", "b"])]
    assert [k.value for k in p.targets.kinds] == ["job", "bounty"] and p.targets.regions == ["tunisia", "eu"]
    assert p.filters.exclude_unpaid is False  # unchecked box is absent
    assert [(m.currency, m.amount) for m in p.filters.min_pay] == [("USD", 30000)]
    assert p.filters.languages == ["en", "fr"] and p.filters.blocked_companies == ["Evil Corp"]
    assert [(i.phrase, i.weight, i.where) for i in p.interests] == [("golang", 1.0, "anywhere")]


@pytest.mark.parametrize("bad", [("skills[0][weight]", "7"), ("skills[0][weight]", "abc"),
                                 ("boost[0][weight]", "x")])
def test_bad_weight_rejected(bad):
    pairs = dict([("skills[0][name]", "go"), ("skills[0][weight]", "1"), ("boost[0][keyword]", "k"),
                  ("boost[0][weight]", "1"), ("kinds", "job")])
    pairs[bad[0]] = bad[1]
    with pytest.raises((ValidationError, ValueError)):
        profile_from_rows(rows_from_form(FormData(list(pairs.items()))))


def test_save_writes_bak_and_valid_yaml(tmp_path):
    path = tmp_path / "profile.yaml"
    path.write_text("old: true\n", encoding="utf-8")
    p = load_profile(ROOT / "profile.example.yaml")
    save_profile(path, p)
    assert (tmp_path / "profile.yaml.bak").read_text(encoding="utf-8") == "old: true\n"
    assert load_profile(path) == p
    assert "Room-mapping" in path.read_text(encoding="utf-8")  # unicode/readable, not escaped
    assert isinstance(yaml.safe_load(path.read_text(encoding="utf-8")), dict)
