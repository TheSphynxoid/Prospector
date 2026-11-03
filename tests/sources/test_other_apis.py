import json
from pathlib import Path

import httpx
import respx

from prospector.models import Kind
from prospector.sources.adzuna import Adzuna
from prospector.sources.freelancer import Freelancer
from prospector.sources.github_bounties import GitHubBounties
from prospector.sources.hn import HackerNewsHiring

FIX = Path(__file__).resolve().parents[1] / "fixtures"


def load(path):
    return json.loads((FIX / path).read_text(encoding="utf-8"))


@respx.mock
def test_adzuna_maps_fields_per_country():
    route = respx.get(url__regex=r"https://api\.adzuna\.com/v1/api/jobs/(fr|de)/search/1.*").mock(
        return_value=httpx.Response(200, json=load("adzuna/fr.json")))
    with httpx.Client() as http:
        leads = Adzuna("id", "key", countries=("fr", "de")).fetch(http)
    assert route.call_count == 2
    assert len(leads) == 4
    assert {l.location_text.split("[")[-1] for l in leads} == {"FR]", "DE]"}
    first = leads[0]
    assert first.company == "Voyages SA" and first.pay_text and "45000" in first.pay_text
    assert first.posted_at is not None
    params = dict(route.calls[0].request.url.params)
    assert params["app_id"] == "id" and params["results_per_page"] == "50"


@respx.mock
def test_hn_one_lead_per_top_level_comment():
    search, item = load("hn/search.json"), load("hn/item.json")
    item["children"].append({"id": 1, "author": None, "text": None, "children": []})  # deleted comment
    respx.get(url__startswith="https://hn.algolia.com/api/v1/search_by_date").mock(
        return_value=httpx.Response(200, json=search))
    respx.get(url__regex=r"https://hn\.algolia\.com/api/v1/items/\d+").mock(
        return_value=httpx.Response(200, json=item))
    with httpx.Client() as http:
        leads = HackerNewsHiring().fetch(http)
    live = [c for c in item["children"] if c.get("text")]
    assert len(leads) == len(live)
    first = leads[0]
    assert first.url == f"https://news.ycombinator.com/item?id={live[0]['id']}"
    assert len(first.title) <= 120 and "<" not in first.title
    assert first.company == "Simple Analytics"


@respx.mock
def test_github_bounty_kind_and_pay():
    data = load("github_bounties/search.json")
    data["items"][0]["labels"].append({"name": "$250"})
    route = respx.get(url__startswith="https://api.github.com/search/issues").mock(
        return_value=httpx.Response(200, json=data))
    with httpx.Client() as http:
        leads = GitHubBounties("tok").fetch(http)
    assert len(leads) == 5 and all(l.kind_hint is Kind.BOUNTY for l in leads)
    assert leads[0].pay_text == "$250 USD fixed"
    assert route.calls[0].request.headers["Authorization"] == "Bearer tok"


@respx.mock
def test_freelancer_budget_to_pay_text():
    data = load("freelancer/golang.json")
    route = respx.get(url__startswith="https://www.freelancer.com/api/projects/0.1/projects/active/").mock(
        return_value=httpx.Response(200, json=data))
    with httpx.Client() as http:
        leads = Freelancer(queries=("golang", "c++")).fetch(http)
    assert route.call_count == 2
    p = data["result"]["projects"][0]
    assert len(leads) == len(data["result"]["projects"])  # deduped across queries
    assert leads[0].url == f"https://www.freelancer.com/projects/{p['seo_url']}"
    assert leads[0].pay_text == "250-750 USD fixed" and leads[0].kind_hint is Kind.GIG
