import pytest

from prospector.models import Kind, Remote
from prospector.profile.model import DEFAULT_WORK_FROM, Profile, Targets
from prospector.rank.reach import competition_factor, lead_level, reach, region_status

WF = list(DEFAULT_WORK_FROM)


@pytest.fixture
def prof():
    return Profile(skills={"go": 1.0}, projects=[],
                   targets=Targets(kinds=list(Kind), regions=["tunisia"], levels=["intern", "junior"]))


@pytest.mark.parametrize("title,body,level", [
    ("Senior Go Engineer", "", "senior"), ("Sr. Backend Dev", "", "senior"),
    ("Staff Software Engineer", "", "lead"), ("Lead Go Developer", "", "lead"),
    ("Principal Engineer", "", "lead"), ("Software Architect", "", "lead"),
    ("Engineering Manager, Platform", "", "lead"), ("Tech Lead - Payments", "", "lead"),
    ("Junior C++ Developer", "", "junior"), ("Stage PFE Développeur Go", "", "intern"),
    ("Software Engineering Intern 2027", "", "intern"), ("Développeur Go confirmé", "", "senior"),
    ("Mid-level Backend Engineer", "", "mid"), ("Graduate Software Engineer", "", "junior"),
    ("Software Engineer", "You have 5+ years of professional experience", "senior"),
    ("Développeur Go", "minimum 3 ans d'expérience", "mid"),
    ("Backend Engineer", "At least 2 years of experience with Go", "junior"),
    ("Software Engineer", "Our team of 40 engineers ships 3 years ahead", None),
    ("Software Engineer", "", None),
])
def test_lead_level(make_lead, title, body, level):
    assert lead_level(make_lead(title=title, body=body)) == level


def test_level_false_friends(make_lead):
    assert lead_level(make_lead(title="Product Manager intern")) == "intern"
    assert lead_level(make_lead(title="Leading fintech hiring junior Go dev")) == "junior"
    assert lead_level(make_lead(title="Lead generation specialist")) is None
    assert lead_level(make_lead(title="Senior", kind=Kind.INTERNSHIP)) == "intern"


@pytest.mark.parametrize("region,status,label", [
    ("US only", "locked", "US only"), ("EMEA", "ok", None), ("Europe", "maybe", "Europe"),
    ("Anywhere in the World", "ok", None), ("Austin, TX", "locked", "US only"),
    (None, "ok", None), ("Canada", "locked", "Canada only"), ("Mars colony", "ok", None),
    ("United States", "locked", "US only"), ("LATAM", "locked", "LATAM only"), ("CET", "maybe", "Europe"),
])
def test_region_status(make_lead, region, status, label):
    assert region_status(make_lead(remote_region=region), WF) == (status, label)


def test_region_mixed_ok(make_lead):
    assert region_status(make_lead(remote_region="USA, EMEA"), WF)[0] == "ok"
    assert region_status(make_lead(remote_region="Europe, Africa"), WF)[0] == "ok"
    assert region_status(make_lead(remote_region="US or Canada"), WF) == ("locked", "US only")


def test_region_ignored_when_not_remote(make_lead):
    assert region_status(make_lead(remote=Remote.NO, remote_region="US only"), WF) == ("ok", None)


def test_reach_combines(make_lead, prof):
    assert reach(make_lead(title="Junior Go dev"), prof) == (1.0, None)
    assert reach(make_lead(title="Go dev", body="3 years of experience"), prof) == (0.75, "Stretch")
    assert reach(make_lead(title="Senior Go dev"), prof) == (0.35, "Too senior")
    assert reach(make_lead(title="Junior Go dev", remote_region="US only"), prof) == (0.35, "US only")
    assert reach(make_lead(title="Junior Go dev", remote_region="Europe"), prof) == (0.75, "Europe")
    assert reach(make_lead(title="Senior bounty", kind=Kind.GIG), prof) == (1.0, None)
    assert reach(make_lead(title="Senior Go dev", remote_region="US only"), prof)[0] == 0.35
    assert reach(make_lead(title="Go dev"), prof) == (1.0, None)


def test_reach_all_levels_is_neutral(make_lead):
    p = Profile(skills={}, projects=[], targets=Targets(kinds=list(Kind), regions=[]))
    assert reach(make_lead(title="Principal Engineer"), p) == (1.0, None)


@pytest.mark.parametrize("bids,factor", [(None, 1.0), (0, 1.0), (10, 1.0), (11, 0.9), (30, 0.9),
                                         (31, 0.8), (50, 0.8), (51, 0.65)])
def test_competition_factor(bids, factor):
    assert competition_factor(bids) == factor


def test_level_words_inside_other_words(make_lead):
    assert lead_level(make_lead(title="Go Engineer at an early-stage startup")) is None
    assert lead_level(make_lead(title="International Backend Engineer")) is None
    assert lead_level(make_lead(title="Co-lead developer relations")) is None
