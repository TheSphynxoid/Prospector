import json
from pathlib import Path

import httpx
import pytest
import respx

from prospector.sources.arbeitnow import Arbeitnow
from prospector.sources.himalayas import Himalayas
from prospector.sources.remoteok import RemoteOK
from prospector.sources.remotive import Remotive

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def fixture(name):
    return json.loads((FIX / name / "sample.json").read_text(encoding="utf-8"))


CASES = [
    (Remotive, "remotive", "https://remotive.com/api/remote-jobs"),
    (RemoteOK, "remoteok", "https://remoteok.com/api"),
    (Himalayas, "himalayas", "https://himalayas.app/jobs/api"),
    (Arbeitnow, "arbeitnow", "https://www.arbeitnow.com/api/job-board-api"),
]


@pytest.mark.parametrize("cls,name,url", CASES)
@respx.mock
def test_maps_fields(cls, name, url):
    respx.get(url__startswith=url).mock(return_value=httpx.Response(200, json=fixture(name)))
    src = cls()
    with httpx.Client() as http:
        leads = src.fetch(http)
    assert src.id == name
    assert len(leads) == 5
    assert all(l.title and l.url.startswith("http") and l.body and l.source_id == name for l in leads)
    assert len({l.external_id for l in leads}) == 5
    assert all(l.posted_at is not None and l.posted_at.tzinfo is not None for l in leads)
    assert all(l.raw_payload for l in leads)


def test_intervals():
    assert (Remotive.interval_hours, RemoteOK.interval_hours, Himalayas.interval_hours,
            Arbeitnow.interval_hours) == (4, 4, 6, 6)


@respx.mock
def test_remoteok_skips_legal_notice():
    data = fixture("remoteok")
    assert "legal" in json.dumps(data[0]).lower()
    respx.get("https://remoteok.com/api").mock(return_value=httpx.Response(200, json=data))
    with httpx.Client() as http:
        leads = RemoteOK().fetch(http)
    assert len(leads) == len(data) - 1


@respx.mock
def test_http_error_raises_for_runner():
    respx.get(url__startswith="https://remotive.com").mock(return_value=httpx.Response(503))
    with httpx.Client() as http, pytest.raises(httpx.HTTPStatusError):
        Remotive().fetch(http)
