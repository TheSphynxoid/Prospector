from pathlib import Path

import pytest

from prospector.models import Kind, Pay
from prospector.profile.filters import apply_hard_filters, pay_meets_min
from prospector.profile.model import Filters, MinPay, Profile, Targets, load_profile

ROOT = Path(__file__).resolve().parents[2]


def profile(**filters):
    return Profile(
        skills={"go": 1.0}, projects=[], boost_keywords={},
        targets=Targets(kinds=[Kind.JOB, Kind.GIG], regions=["remote"]),
        filters=Filters(**filters),
    )


def test_load_example_profile():
    p = load_profile(ROOT / "profile.example.yaml")
    assert len(p.projects) >= 7
    assert set(p.targets.kinds) == set(Kind)
    assert all(len(pr.writeup) > 80 for pr in p.projects)


@pytest.mark.parametrize("filters,lead_kw,reason", [
    ({"blocked_companies": ["Evil Corp"]}, {"company": "EVIL CORP Inc."}, "blocked company: Evil Corp"),
    ({"blocked_keywords": ["php"]}, {"title": "Senior PHP dev"}, "blocked keyword: php"),
    ({}, {"body": "This is an unpaid internship"}, "unpaid"),
    ({}, {"body": "Stage non rémunéré"}, "unpaid"),
    ({}, {"kind": Kind.BOUNTY}, "kind not targeted: bounty"),
    ({"languages": ["fr", "en"]}, {"languages": ["de"]}, "language: de"),
    ({"min_pay": [MinPay(currency="EUR", period="month", amount=2000)]},
     {"pay": Pay(1000, 1500, "EUR", "month")}, "below min pay"),
])
def test_filter_reasons(make_lead, filters, lead_kw, reason):
    assert apply_hard_filters(make_lead(**lead_kw), profile(**filters)) == reason


def test_unpaid_allowed_when_not_excluded(make_lead):
    assert apply_hard_filters(make_lead(body="unpaid"), profile(exclude_unpaid=False)) is None


def test_min_pay_ignored_for_other_currency(make_lead):
    p = profile(min_pay=[MinPay(currency="EUR", period="month", amount=2000)])
    assert apply_hard_filters(make_lead(pay=Pay(100, 100, "USD", "hour")), p) is None


def test_no_language_detected_passes(make_lead):
    assert apply_hard_filters(make_lead(languages=[]), profile()) is None


def test_clean_lead_passes(make_lead):
    assert apply_hard_filters(make_lead(), profile()) is None


def test_pay_meets_min():
    p = profile(min_pay=[MinPay(currency="EUR", period="month", amount=2000)])
    assert pay_meets_min(Pay(2500, 3000, "EUR", "month"), p) is True
    assert pay_meets_min(Pay(1000, 1500, "EUR", "month"), p) is False
    assert pay_meets_min(Pay(10, 10, "USD", "hour"), p) is None
    assert pay_meets_min(None, p) is None
