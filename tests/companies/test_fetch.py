import json
from datetime import UTC
from pathlib import Path

import httpx
import pytest
import respx

from prospector.companies.fetch import BoardError, fetch_board, is_tech_role
from prospector.store.companies import CompanyRepo
from prospector.store.db import connect

FIX = Path(__file__).parent.parent / "fixtures"
GH = "https://boards-api.greenhouse.io/v1/boards/cloudflare/jobs?content=true"
LV = "https://api.lever.co/v0/postings/palantir?mode=json"
AB = "https://api.ashbyhq.com/posting-api/job-board/ramp"


def fixture(board):
    return json.loads((FIX / board / "sample.json").read_text(encoding="utf-8"))


def company(board, token):
    repo = CompanyRepo(connect(":memory:"))
    repo.add(board, token)
    return repo.list()[0]


@pytest.mark.parametrize("title", ["Backend Engineer", "Software Engineering Intern", "SRE", "Golang Developer",
                                   "Data Platform Engineer", "Sales Engineer", "C++ Developer", "New Grad, Platform",
                                   "Développeur Go", "Embedded Firmware Lead"])
def test_is_tech_role_true(title):
    assert is_tech_role(title)


@pytest.mark.parametrize("title", ["Account Executive", "Senior Recruiter", "Legal Counsel", "Marketing Manager",
                                   "Customer Support Specialist", "Office Manager", "Go-to-Market Lead",
                                   "Sales Development Representative", "Finance Data Analyst"])
def test_is_tech_role_false(title):
    assert not is_tech_role(title)


@respx.mock
def test_greenhouse_maps_fields():
    respx.get(GH).respond(json=fixture("greenhouse"))
    name, leads = fetch_board(httpx.Client(), company("greenhouse", "cloudflare"))
    assert name == "Cloudflare"
    assert [l.title for l in leads] == ["AI Security Research & Red Team Engineer", "Capacity Engineer",
                                        "Software Engineering Intern"]
    first = leads[0]
    assert first.external_id == "greenhouse:cloudflare:8097321" and first.source_id == "company_boards"
    assert first.url.startswith("https://boards.greenhouse.io/cloudflare/jobs/8097321")
    assert first.company == "Cloudflare" and first.posted_at.tzinfo is not None
    assert first.location_text == "Hybrid"
    assert leads[2].location_text == "Remote (EMEA)"


@respx.mock
def test_greenhouse_content_unescaped():
    respx.get(GH).respond(json=fixture("greenhouse"))
    _, leads = fetch_board(httpx.Client(), company("greenhouse", "cloudflare"))
    from prospector.normalize.normalize import clean_text
    assert "&lt;" not in leads[0].body
    body = clean_text(leads[0].body, keep_lines=True)
    assert "&lt;" not in body and "<p>" not in body and "<div" not in body
    assert "At Cloudflare, we are on a mission" in body


@respx.mock
def test_lever_maps_fields():
    respx.get(LV).respond(json=fixture("lever"))
    name, leads = fetch_board(httpx.Client(), company("lever", "palantir"))
    assert name is None
    assert [l.external_id for l in leads] == ["lever:palantir:10dfc8bc-99ad-4ca2-ab76-853cb90a92c2",
                                              "lever:palantir:ab7e3425-81d5-4705-a7b5-cd60c8a45cdb",
                                              "lever:palantir:remote-0001"]
    assert leads[0].company == "Palantir" and leads[0].location_text == "London, United Kingdom"
    assert leads[0].posted_at.year == 2024 and leads[0].posted_at.tzinfo == UTC
    assert leads[0].url == "https://jobs.lever.co/palantir/10dfc8bc-99ad-4ca2-ab76-853cb90a92c2"
    assert leads[2].location_text == "Remote (Europe, United Kingdom)"
    assert leads[0].body.strip()


@respx.mock
def test_ashby_maps_fields_and_skips_unlisted():
    respx.get(AB).respond(json=fixture("ashby"))
    _, leads = fetch_board(httpx.Client(), company("ashby", "ramp"))
    titles = [l.title for l in leads]
    assert titles == ["AI Solutions Engineer", "Security Engineer, Cloud", "Mobile Engineer, Android"]
    assert leads[0].external_id == "ashby:ramp:8efd3a0a-fc66-46e2-9415-bffba10e2919"
    assert leads[0].location_text.startswith("Remote (New York, NY (HQ), San Francisco, CA")
    assert leads[1].location_text == "Remote (New York, NY (HQ), Canada, US, Miami, FL)"
    assert leads[0].company == "Ramp" and leads[0].posted_at.tzinfo is not None


@respx.mock
@pytest.mark.parametrize("board,url,payload", [
    ("lever", "https://api.lever.co/v0/postings/acme?mode=json", {"error": "x"}),
    ("greenhouse", "https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true", []),
    ("ashby", "https://api.ashbyhq.com/posting-api/job-board/acme", {"jobs": "nope"}),
])
def test_board_bad_shape_raises(board, url, payload):
    respx.get(url).respond(json=payload)
    with pytest.raises(BoardError):
        fetch_board(httpx.Client(), company(board, "acme"))


@respx.mock
def test_board_not_json_raises():
    respx.get("https://api.lever.co/v0/postings/acme?mode=json").respond(200, text="<html>")
    with pytest.raises(BoardError):
        fetch_board(httpx.Client(), company("lever", "acme"))


def test_title_cased_token_company():
    assert company("lever", "sensor-tower").display_name == "Sensor Tower"
