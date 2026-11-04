from datetime import date

import pytest
from pydantic import ValidationError

from prospector.models import Kind, Status
from prospector.profile import interests
from prospector.profile.form import save_profile
from prospector.profile.model import About, Interest, Profile, load_profile

BASE = {"skills": {"go": 1.0}, "projects": [], "targets": {"kinds": ["job"], "regions": []}}


def test_legacy_boost_keywords_become_interests():
    p = Profile(**BASE, boost_keywords={"rust": 0.5, " go ": 0.3})
    assert p.interests == [Interest(phrase="rust", weight=0.5, where="anywhere"),
                           Interest(phrase="go", weight=0.3, where="anywhere")]
    assert "boost_keywords" not in p.model_dump()


def test_interests_win_over_legacy():
    p = Profile(**BASE, boost_keywords={"rust": 0.5}, interests=[{"phrase": "zig", "weight": 1}])
    assert [i.phrase for i in p.interests] == ["zig"]


@pytest.mark.parametrize("bad", [{"phrase": "x", "weight": 0}, {"phrase": "x", "weight": 1.5},
                                 {"phrase": "", "weight": 0.5}, {"phrase": "a" * 81, "weight": 0.5},
                                 {"phrase": "x", "weight": 0.5, "where": "body"}])
def test_interest_bounds(bad):
    with pytest.raises(ValidationError):
        Interest(**bad)


@pytest.mark.parametrize("phrase,text,hit", [
    ("go", "Google ads", False), ("go", "Go developer", True), ("go", "golang", False),
    ("C++", "Senior C++ engineer", True), ("C++", "C+++ x", False), ("C#", "C# and .NET", True),
    ("C", "C# dev", False), ("node.js", "Node.js backend", True), (".NET", "ASP.NET core", False),
    (".NET", "A .NET shop", True), ("machine learning", "Machine  learning", False),
    ("machine learning", "machine learning role", True)])
def test_interest_literal_tokens(phrase, text, hit):
    assert interests.matches(Interest(phrase=phrase, weight=0.5), text, "") is hit


def test_title_only():
    i = Interest(phrase="rust", weight=0.5, where="title")
    assert not interests.matches(i, "Backend dev", "we use rust") and interests.matches(i, "Rust dev", "")
    assert interests.matches(Interest(phrase="rust", weight=0.5), "Backend dev", "we use rust")


def test_negative_weight_lowers_score(make_lead):
    lead = make_lead(title="Embedded C++ role", body="WordPress maintenance too")
    ints = [Interest(phrase="C++", weight=0.9), Interest(phrase="WordPress", weight=-0.6)]
    assert interests.keyword_score(lead, ints) == pytest.approx(0.1)
    assert interests.keyword_score(lead, [Interest(phrase="WordPress", weight=-0.6)]) == 0.0


def test_preview_counts_and_examples(wctx, make_lead):
    for i, t in enumerate(["Rust backend", "Rust CLI", "Go API", "Rust embedded"]):
        wctx.leads.insert(make_lead(canonical_url=f"u{i}", title=t))
    lid = wctx.leads.insert(make_lead(canonical_url="d", title="Rust dismissed"))
    wctx.leads.set_status(lid, Status.DISMISSED)
    n, titles = interests.preview(wctx.leads, Interest(phrase="rust", weight=0.5))
    assert n == 3 and len(titles) == 3 and all("Rust" in t for t in titles)


def test_suggest_from_titles():
    titles = ["Embedded Linux engineer", "Embedded Linux drivers", "Senior Go developer for embedded linux",
              "Le développeur Go", "Go developer"]
    out = interests.suggest(titles, known={"go"})
    assert "embedded linux" in out and "embedded" in out
    assert "go" not in out and "le" not in out and "for" not in out and "developer" in out


def test_about_round_trip(tmp_path):
    p = Profile(**BASE, about=About(
        name="Hamza", headline="C++/Go engineer", bio="Builds things.", location="Tunis", timezone="Africa/Tunis",
        languages=[{"language": "Arabic", "level": "native"}, {"language": "English", "level": "fluent"}],
        years_experience=4, highlights=["Shipped a room-mapping engine"],
        education=[{"school": "ENIT", "degree": "Engineering", "year": 2027}],
        availability={"hours_per_week": 30, "earliest_start": date(2026, 12, 1), "open_to": ["gigs", "internship"]},
        links={"github": "https://github.com/x"}))
    path = tmp_path / "p.yaml"
    save_profile(path, p)
    assert load_profile(path) == p and "boost_keywords" not in path.read_text(encoding="utf-8")


def test_about_bounds():
    with pytest.raises(ValidationError):
        About(languages=[{"language": "x", "level": "godlike"}])
    with pytest.raises(ValidationError):
        About(years_experience=99)
    assert Kind
