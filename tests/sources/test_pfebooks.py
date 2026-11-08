import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import respx

from prospector.models import Kind
from prospector.normalize.normalize import normalize
from prospector.sources.pfebooks import API, PfeBooks

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "pfebooks" / "listings.json"
ITEMS = json.loads(FIXTURE.read_text(encoding="utf-8"))
ROBOTS = "User-agent: *\nDisallow: /wp-includes/\n"


def _robots():
    respx.get("https://pfebooks.com/robots.txt").mock(return_value=httpx.Response(200, text=ROBOTS))


def _page(items, pages=1):
    return httpx.Response(200, json=items, headers={"X-WP-TotalPages": str(pages)})


@respx.mock
def test_parses_listings_and_skips_filled():
    _robots()
    route = respx.get(API).mock(return_value=_page(ITEMS))
    with httpx.Client() as http:
        leads = PfeBooks().fetch(http)
    assert len(leads) == 3  # the fixture's fourth item is filled
    params = route.calls[0].request.url.params
    assert params["job-categories"] == "1285,1289,1282" and params["per_page"] == "100" and params["page"] == "1"
    first = leads[0]
    assert first.external_id == "10037" and first.url.startswith("https://pfebooks.com/stages/")
    assert first.title.startswith("Cloud-Native Containerized Deployment")
    assert first.company == "Integration Objects" and first.kind_hint == Kind.PFE
    assert first.location_text == "Tunis, Tunisie"
    assert first.posted_at.tzinfo == UTC and first.posted_at.year == 2026
    assert "Postuler : careers@integrationobjects.com" in first.body and "Niveau : Niveau ouvert" in first.body


@respx.mock
def test_remote_type_reaches_the_location():
    _robots()
    respx.get(API).mock(return_value=_page(ITEMS))
    with httpx.Client() as http:
        second = PfeBooks().fetch(http)[1]
    assert second.location_text == "Tunis, Tunisie (Télétravail)"
    assert normalize(second).remote.value == "yes"


@respx.mock
def test_normalized_body_keeps_the_apply_line():
    _robots()
    respx.get(API).mock(return_value=_page(ITEMS))
    with httpx.Client() as http:
        lead = normalize(PfeBooks().fetch(http)[0])
    assert "careers@integrationobjects.com" in lead.body and lead.kind == Kind.PFE
    assert lead.locations == ["Tunis, Tunisie"]


@respx.mock
def test_follows_pages_up_to_the_total():
    _robots()
    route = respx.get(API).mock(side_effect=[_page(ITEMS[:1], pages=2), _page(ITEMS[1:2], pages=2)])
    with httpx.Client() as http:
        leads = PfeBooks().fetch(http)
    assert [l.external_id for l in leads] == ["10037", "10052"] and route.call_count == 2


@respx.mock
def test_stops_at_max_pages(monkeypatch):
    import prospector.sources.pfebooks as mod
    monkeypatch.setattr(mod, "MAX_PAGES", 2)
    _robots()
    route = respx.get(API).mock(return_value=_page(ITEMS[:1], pages=50))
    with httpx.Client() as http:
        PfeBooks().fetch(http)
    assert route.call_count == 2


@respx.mock
def test_respects_robots():
    respx.get("https://pfebooks.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /wp-json/\n"))
    route = respx.get(API).mock(return_value=_page(ITEMS))
    with httpx.Client() as http:
        assert PfeBooks().fetch(http) == []
    assert not route.called


def test_registered_and_enabled_by_default():
    from prospector.config import Settings
    from prospector.sources.registry import known_source_ids
    assert "pfebooks" in known_source_ids()
    assert "pfebooks" in Settings.model_fields["enabled_sources"].default


def test_posted_at_is_the_gmt_date():
    from prospector.sources.pfebooks import _posted
    assert _posted("2026-11-05T14:09:54") == datetime(2026, 11, 5, 14, 9, 54, tzinfo=UTC)
    assert _posted(None) is None and _posted("garbage") is None
