from prospector.models import Kind
from prospector.profile.model import Profile, Targets
from prospector.rank.stage2 import SYSTEM, _cache_key, _user_prompt


def prof(levels=("intern", "junior")):
    return Profile(skills={"go": 1}, projects=[],
                   targets=Targets(kinds=list(Kind), regions=[], levels=list(levels), work_from=["emea", "tunisia"]))


def test_prompt_has_level_and_region(make_lead):
    p = _user_prompt(make_lead(), prof())
    assert "CANDIDATE LEVEL: intern, junior" in p and "CAN WORK FROM: emea, tunisia" in p


def test_cache_key_changes_with_levels(make_lead):
    lead = make_lead()
    assert _cache_key(lead, prof()) != _cache_key(lead, prof(("junior", "mid")))
    assert _cache_key(lead, prof()) == _cache_key(lead, prof())
    assert _cache_key(lead, prof()).startswith(f"llm:{lead.content_hash}:")


def test_system_asks_for_level_and_location():
    assert "well above the candidate's level" in SYSTEM and "cannot work from" in SYSTEM
