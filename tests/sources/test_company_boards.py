import json
from pathlib import Path

import httpx
import pytest
import respx

from prospector.config import Settings
from prospector.sources.company_boards import CompanyBoards
from prospector.store.companies import CompanyRepo
from prospector.store.db import connect

FIX = Path(__file__).parent.parent / "fixtures"


def repo():
    return CompanyRepo(connect(":memory:"))


@respx.mock
def test_board_bad_shape_is_company_error():
    r = repo()
    r.add("lever", "broken")
    r.add("ashby", "ramp")
    respx.get("https://api.lever.co/v0/postings/broken?mode=json").respond(json={"error": "x"})
    respx.get("https://api.ashbyhq.com/posting-api/job-board/ramp").respond(
        json=json.loads((FIX / "ashby" / "sample.json").read_text(encoding="utf-8")))
    leads = CompanyBoards(r).fetch(httpx.Client())
    assert len(leads) == 3
    by = {c.token: c for c in r.list()}
    assert by["broken"].failures == 1 and by["broken"].last_error
    assert by["ramp"].last_count == 3 and by["ramp"].failures == 0


@respx.mock
def test_source_records_ok_and_pauses():
    r = repo()
    r.add("lever", "gone")
    respx.get("https://api.lever.co/v0/postings/gone?mode=json").respond(404)
    src = CompanyBoards(r)
    for _ in range(3):
        r.conn.execute("UPDATE companies SET last_checked = NULL")
        with pytest.raises(httpx.HTTPError):  # every company in the batch failed: the source reports it
            src.fetch(httpx.Client())
    c = r.list()[0]
    assert c.state == "paused" and c.failures == 3 and "404" in c.last_error


def test_empty_batch_is_fine():
    assert CompanyBoards(repo()).fetch(httpx.Client()) == []


@respx.mock
def test_source_batch_limit():
    r = repo()
    for i in range(45):
        r.add("lever", f"c{i}")
    route = respx.get(url__regex=r"https://api\.lever\.co/v0/postings/.*").respond(json=[])
    CompanyBoards(r).fetch(httpx.Client())
    assert route.call_count == 40 and CompanyBoards.BATCH == 40
    assert sum(1 for c in r.list() if c.last_checked) == 40


def test_registered_and_default(tmp_path):
    from prospector.sources.registry import build_sources
    from prospector.store.mail import MailRepo
    s = Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p", data_dir=tmp_path)
    assert "company_boards" in s.enabled_sources
    srcs = {x.id: x for x in build_sources(s, MailRepo(connect(":memory:")))}
    cb = srcs["company_boards"]
    assert cb.interval_hours == 1 and cb.may_be_empty is True
