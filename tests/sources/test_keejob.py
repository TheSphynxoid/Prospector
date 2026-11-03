from pathlib import Path

import httpx
import respx

from prospector.sources.keejob import FEED, Keejob

RSS = (Path(__file__).resolve().parents[1] / "fixtures" / "keejob" / "rss.xml").read_text(encoding="utf-8")
ROBOTS_OK = "User-agent: *\nDisallow: /api/\n"


@respx.mock
def test_keejob_parses_feed():
    respx.get("https://www.keejob.com/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS_OK))
    respx.get(FEED).mock(return_value=httpx.Response(200, text=RSS))
    with httpx.Client() as http:
        leads = Keejob().fetch(http)
    assert len(leads) == 6
    first = leads[0]
    assert first.title == "Gestionnaire de Portefeuille – Nabeul"
    assert first.company == "EL AMEL MICROFINANCE"
    assert first.location_text == "Nabeul, Tunisia"
    assert first.url.startswith("https://www.keejob.com/offres-emploi/248572/")
    assert first.external_id == "248572"
    assert all(l.posted_at is not None and l.body for l in leads)


@respx.mock
def test_keejob_respects_robots():
    respx.get("https://www.keejob.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /rss/\n"))
    feed = respx.get(FEED).mock(return_value=httpx.Response(200, text=RSS))
    with httpx.Client() as http:
        assert Keejob().fetch(http) == []
    assert not feed.called
