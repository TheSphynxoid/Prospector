from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
import respx

from prospector.models import Kind
from prospector.sources import gsoc
from prospector.sources.gsoc import GSoC
from prospector.sources.outreachy import URL as OUTREACHY_URL
from prospector.sources.outreachy import Outreachy, parse_deadline

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def text(name):
    return (FIX / name).read_text(encoding="utf-8")


def mock_gsoc():
    respx.get("https://summerofcode.withgoogle.com/api/program/").mock(
        return_value=httpx.Response(200, text=text("gsoc/programs.json")))
    respx.get("https://summerofcode.withgoogle.com/api/program/2026/organizations/").mock(
        return_value=httpx.Response(200, text=text("gsoc/orgs.json")))


@respx.mock
def test_gsoc_open_program_filters_tags(monkeypatch):
    monkeypatch.setattr(gsoc, "_now", lambda: datetime(2026, 3, 1, tzinfo=UTC))
    mock_gsoc()
    with httpx.Client() as http:
        leads = GSoC().fetch(http)
    assert [l.title for l in leads] == ["GSoC 2026: Kiwix", "GSoC 2026: MetaCall"]
    lead = leads[0]
    assert lead.kind_hint is Kind.INTERNSHIP and lead.deadline == date(2026, 3, 31)
    assert lead.url == "https://summerofcode.withgoogle.com/programs/2026/organizations/kiwix"
    assert lead.external_id == "2026:kiwix" and "c++" in lead.body and lead.location_text == "Remote"


@respx.mock
def test_gsoc_closed_program_empty(monkeypatch):
    monkeypatch.setattr(gsoc, "_now", lambda: datetime(2026, 11, 5, tzinfo=UTC))
    mock_gsoc()
    with httpx.Client() as http:
        assert GSoC().fetch(http) == []


@respx.mock
@pytest.mark.parametrize("body", ['{"weird": 1}', '[{"slug": "2027"}]', "[]"])
def test_gsoc_bad_shape_empty(body):
    respx.get("https://summerofcode.withgoogle.com/api/program/").mock(return_value=httpx.Response(200, text=body))
    with httpx.Client() as http:
        assert GSoC().fetch(http) == []


@respx.mock
def test_outreachy_parses_open_projects():
    respx.get(OUTREACHY_URL).mock(return_value=httpx.Response(200, text=text("outreachy/projects.html")))
    with httpx.Client() as http:
        leads = Outreachy().fetch(http)
    assert len(leads) == 8  # closed projects are skipped
    git = leads[0]
    assert git.title == "Outreachy: Implement promisor remote fetch ordering (Git)"
    assert git.url == f"{OUTREACHY_URL}#git-implement-promisor-remote-fetch-ordering"
    assert git.deadline == date(2026, 11, 9) and git.kind_hint is Kind.INTERNSHIP
    assert "C programming language" in git.body and git.company == "Git"


@respx.mock
def test_outreachy_no_blocks_empty():
    respx.get(OUTREACHY_URL).mock(return_value=httpx.Response(200, text="<html><body>Applications are closed</body></html>"))
    with httpx.Client() as http:
        assert Outreachy().fetch(http) == []


@pytest.mark.parametrize("raw,day", [("Nov. 9, 2026 at 4pm UTC", date(2026, 11, 9)),
                                     ("Sept. 30, 2026", date(2026, 9, 30)), ("March 3, 2027", date(2027, 3, 3)),
                                     ("soon", None)])
def test_parse_deadline(raw, day):
    assert parse_deadline(raw) == day
