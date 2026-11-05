from pathlib import Path

import httpx
import pytest
import respx

from prospector.models import Kind
from prospector.sources.codeur import Codeur, budget_to_pay
from prospector.sources.tunisietravail import QUERIES, TunisieTravail

FIX = Path(__file__).resolve().parents[1] / "fixtures"
ALLOW = "User-agent: *\nDisallow: /wp-admin/\n"


def text(name):
    return (FIX / name).read_text(encoding="utf-8")


@respx.mock
def test_tunisietravail_maps_and_filters():
    respx.get("https://www.tunisietravail.net/robots.txt").mock(return_value=httpx.Response(200, text=ALLOW))
    route = respx.get(url__startswith="https://www.tunisietravail.net/wp-json/wp/v2/posts").mock(
        return_value=httpx.Response(200, text=text("tunisietravail/posts.json")))
    with httpx.Client() as http:
        leads = TunisieTravail().fetch(http)
    assert route.call_count == len(QUERIES)
    titles = [l.title for l in leads]
    assert len(leads) == 2 and all("Développeur" in t for t in titles)  # sales and accounting posts dropped
    lead = leads[0]
    assert lead.external_id == "133725" and lead.location_text == "Tunisia" and lead.url.startswith("https://")
    assert lead.posted_at.utcoffset() is not None and lead.body


@pytest.mark.parametrize("title,keep", [("Responsable du Développement Commercial", False),
                                        ("Mecamarket recrute Développeur Full Stack Junior", True),
                                        ("Stage PFE Data Science", True), ("Boraplast recrute Comptable", False),
                                        ("Ingénieur DevOps", True)])
def test_tunisietravail_tech_filter(title, keep):
    from prospector.sources.tunisietravail import is_tech
    assert is_tech(title) is keep


@respx.mock
def test_tunisietravail_robots_block():
    respx.get("https://www.tunisietravail.net/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /\n"))
    with httpx.Client() as http:
        assert TunisieTravail().fetch(http) == []


@respx.mock
def test_codeur_maps_budget():
    respx.get("https://www.codeur.com/robots.txt").mock(
        return_value=httpx.Response(200, text="User-Agent: *\nDisallow: /system/projects/\nDisallow: /*?*\n"))
    respx.get("https://www.codeur.com/projects/c/developpement.rss").mock(
        return_value=httpx.Response(200, text=text("codeur/rss.xml")))
    with httpx.Client() as http:
        leads = Codeur().fetch(http)
    assert len(leads) == 4 and all(l.kind_hint is Kind.GIG and l.location_text == "Remote" for l in leads)
    assert leads[0].external_id == "492379" and leads[0].pay_text == "0-500 EUR fixed"
    assert leads[0].url == "https://www.codeur.com/projects/492379-recherche-un-developpeur"
    assert leads[0].posted_at is not None


@pytest.mark.parametrize("raw,pay", [("Moins de 500 €", "0-500 EUR fixed"), ("500 € à 1 000 €", "500-1000 EUR fixed"),
                                     ("1 000 € à 10 000 €", "1000-10000 EUR fixed"),
                                     ("10 000 € et plus", "10000 EUR fixed"), ("Demande de devis", None)])
def test_budget_to_pay(raw, pay):
    assert budget_to_pay(f"<p>Budget : {raw} - Catégories : API</p>") == pay


@respx.mock
def test_empty_responses():
    respx.get("https://www.tunisietravail.net/robots.txt").mock(return_value=httpx.Response(200, text=ALLOW))
    respx.get(url__startswith="https://www.tunisietravail.net/wp-json/wp/v2/posts").mock(
        return_value=httpx.Response(200, json=[]))
    respx.get("https://www.codeur.com/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://www.codeur.com/projects/c/developpement.rss").mock(return_value=httpx.Response(
        200, text='<?xml version="1.0"?><rss version="2.0"><channel><title>x</title></channel></rss>'))
    with httpx.Client() as http:
        assert TunisieTravail().fetch(http) == [] and Codeur().fetch(http) == []
