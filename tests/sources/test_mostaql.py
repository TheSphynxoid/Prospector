from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from prospector.models import Kind
from prospector.sources.mostaql import URL, Mostaql

FEED = (Path(__file__).resolve().parents[1] / "fixtures" / "mostaql" / "rss.xml").read_text(encoding="utf-8")
ROBOTS = "User-agent: *\nDisallow: /search*\nDisallow: /ajax/\n"


def _fetch(robots=ROBOTS, feed=FEED):
    respx.get("https://mostaql.com/robots.txt").mock(return_value=httpx.Response(200, text=robots))
    route = respx.get(URL).mock(return_value=httpx.Response(200, text=feed))
    with httpx.Client() as http:
        return Mostaql().fetch(http), route


@respx.mock
def test_mostaql_maps_development_projects():
    leads, _ = _fetch()
    assert len(leads) == 3  # the item without a link is dropped
    lead = leads[0]
    assert lead.source_id == "mostaql" and lead.external_id == "1291414"
    assert lead.url == "https://mostaql.com/project/1291414"  # the /go/ link only redirects here
    assert lead.title == "تصميم اداة تحكم بالمستخدمين والمنصة" and lead.body
    assert lead.kind_hint is Kind.GIG and lead.location_text == "Remote"
    assert lead.posted_at == datetime(2026, 11, 7, 14, 31, 44, tzinfo=UTC)
    assert "<item>" in lead.raw_payload


@respx.mock
def test_mostaql_respects_robots():
    leads, route = _fetch(robots="User-agent: *\nDisallow: /\n")
    assert leads == [] and route.call_count == 0


@respx.mock
def test_mostaql_empty_feed():
    empty = '<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'
    leads, _ = _fetch(feed=empty)
    assert leads == []


def test_mostaql_is_registered_and_on_by_default():
    import prospector.sources.adapters  # noqa: F401  (registers adapters)
    from prospector.config import Settings
    from prospector.sources.registry import known_source_ids
    assert "mostaql" in known_source_ids()
    assert "mostaql" in Settings.model_fields["enabled_sources"].default
