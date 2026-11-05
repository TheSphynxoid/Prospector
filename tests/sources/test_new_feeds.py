from pathlib import Path

import httpx
import pytest
import respx

from prospector.sources.golangprojects import Golangprojects
from prospector.sources.jobicy import Jobicy
from prospector.sources.weworkremotely import FEEDS, WeWorkRemotely

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def text(name):
    return (FIX / name).read_text(encoding="utf-8")


def mock_all():
    for url in FEEDS:  # the same sample for each category: dedupe by guid keeps 4
        respx.get(url).mock(return_value=httpx.Response(200, text=text("weworkremotely/backend.rss")))
    respx.get(url__startswith="https://jobicy.com/api/v2/remote-jobs").mock(
        return_value=httpx.Response(200, text=text("jobicy/sample.json")))
    respx.get("https://www.golangprojects.com/rss.xml").mock(
        return_value=httpx.Response(200, text=text("golangprojects/rss.xml")))


@pytest.mark.parametrize("cls,sid,n,dated", [(WeWorkRemotely, "weworkremotely", 4, True),
                                              (Jobicy, "jobicy", 4, True),
                                              (Golangprojects, "golangprojects", 4, False)])
@respx.mock
def test_feed_maps_fields(cls, sid, n, dated):
    mock_all()
    with httpx.Client() as http:
        leads = cls().fetch(http)
    assert len(leads) == n and len({l.external_id for l in leads}) == n
    assert all(l.source_id == sid and l.title and l.url.startswith("https://") and l.body and l.raw_payload
               for l in leads)
    if dated:
        assert all(l.posted_at is not None and l.posted_at.tzinfo is not None for l in leads)


def test_intervals():
    assert (WeWorkRemotely.interval_hours, Jobicy.interval_hours, Golangprojects.interval_hours) == (4, 6, 6)


@respx.mock
def test_wwr_splits_company_and_region():
    mock_all()
    with httpx.Client() as http:
        lead = WeWorkRemotely().fetch(http)[0]
    assert lead.company == "Smartsheet" and lead.title == "Principal Software Engineer (Remote Eligible in Bulgaria)"
    assert lead.location_text == "Remote (Anywhere in the World)"


@respx.mock
def test_jobicy_region_and_pay():
    mock_all()
    with httpx.Client() as http:
        leads = Jobicy().fetch(http)
    by_geo = {l.location_text for l in leads}
    assert "Remote (EMEA)" in by_geo and "Remote (USA)" in by_geo
    paid = [l for l in leads if l.pay_text]
    assert [l.pay_text for l in paid] == ["217000-303900 USD per year"]
    assert all(l.url.startswith("https://jobicy.com/jobs/") for l in leads)  # Jobicy's terms: link to their page


@respx.mock
def test_golangprojects_company_from_title():
    mock_all()
    with httpx.Client() as http:
        lead = Golangprojects().fetch(http)[0]
    assert lead.title == "Senior Software Engineer" and lead.company == "Sotheby’s"


@respx.mock
def test_feeds_empty_ok():
    empty_rss = '<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
    for url in FEEDS:
        respx.get(url).mock(return_value=httpx.Response(200, text=empty_rss))
    respx.get(url__startswith="https://jobicy.com/api/v2/remote-jobs").mock(
        return_value=httpx.Response(200, json={"jobs": []}))
    respx.get("https://www.golangprojects.com/rss.xml").mock(return_value=httpx.Response(200, text=empty_rss))
    with httpx.Client() as http:
        assert WeWorkRemotely().fetch(http) == [] and Jobicy().fetch(http) == [] and Golangprojects().fetch(http) == []


def test_jobicy_pay_tolerates_decimal_strings():
    from prospector.sources.jobicy import _pay
    assert _pay({"salaryMin": "55000.50", "salaryMax": "70000", "salaryCurrency": "EUR",
                 "salaryPeriod": "yearly"}) == "55000-70000 EUR per year"
    assert _pay({"salaryMin": "n/a", "salaryCurrency": "EUR"}) is None
