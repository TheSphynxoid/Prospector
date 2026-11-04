import pytest
from fastapi.testclient import TestClient

from prospector.models import Kind, Remote, Status
from tests.web.conftest import TAILNET


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


@pytest.fixture
def leads(ctx, make_lead):
    ctx.leads.insert(make_lead(canonical_url="https://e/job", title="Job lead", kind=Kind.JOB, remote=Remote.YES))
    ctx.leads.insert(make_lead(canonical_url="https://e/gig", title="Gig lead", kind=Kind.GIG, remote=Remote.NO))


def test_apply_with_every_field_empty(client, leads):
    # What the filter form sends when nothing is chosen ("Any" everywhere).
    r = client.get("/leads?tab=new&kind=&remote=&source=&min_score=&sort=score")
    assert r.status_code == 200 and "Job lead" in r.text and "Gig lead" in r.text


def test_one_filter_others_empty(client, leads):
    r = client.get("/leads?tab=new&kind=gig&remote=&source=&min_score=&sort=score")
    assert r.status_code == 200 and "Gig lead" in r.text and "Job lead" not in r.text
    r = client.get("/leads?tab=new&kind=&remote=yes&min_score=")
    assert "Job lead" in r.text and "Gig lead" not in r.text


@pytest.mark.parametrize("query", ["tab=bogus", "page=abc", "page=-3", "min_score=abc", "kind=nope", "remote=maybe",
                                   "sort=weird", "min_score=nan", "min_score=inf"])
def test_bad_values_fall_back(client, leads, query):
    r = client.get(f"/leads?{query}")
    assert r.status_code == 200 and "Job lead" in r.text


def test_min_score_clamped_and_kept_in_form(ctx, client, leads):
    r = client.get("/leads?min_score=0.5")
    assert 'name="min_score" type="number" step="0.05" min="0" max="1" placeholder="0–1" value="0.5"' in r.text
    r = client.get("/leads?min_score=7")
    assert 'value="1.0"' in r.text


def test_empty_filters_not_in_pagination_links(ctx, client, make_lead):
    for i in range(51):
        ctx.leads.insert(make_lead(canonical_url=f"https://e/{i}"))
    page = client.get("/leads?tab=new&kind=&remote=&source=&min_score=&sort=date").text
    assert "page=2" in page
    nxt = page[page.index("page=2") - 120:page.index("page=2")]
    assert "kind=" not in nxt and "min_score=" not in nxt and "sort=date" in nxt


def test_tab_value_still_selects(client, ctx, make_lead):
    lid = ctx.leads.insert(make_lead(canonical_url="https://e/s", title="Starred lead"))
    ctx.leads.set_status(lid, Status.STARRED)
    assert "Starred lead" in client.get("/leads?tab=starred&kind=&remote=").text


def test_source_is_a_dropdown(client, leads):
    page = client.get("/leads?source=hn").text
    assert '<select name="source">' in page and '<option value="hn" selected>' in page
    assert '<option value="">Any</option>' in page


def test_tabs_keep_filters(client, leads):
    page = client.get("/leads?tab=new&kind=gig&remote=&min_score=0.3&q=go").text
    starred = page[page.index('href="/leads?tab=starred'):].split('"')[1]
    assert "kind=gig" in starred and "min_score=0.3" in starred and "q=go" in starred and "remote=" not in starred


def test_clear_filters_link_only_when_filtering(client, leads):
    assert "Clear filters" not in client.get("/leads?tab=starred").text
    page = client.get("/leads?tab=starred&kind=gig").text
    assert 'href="/leads?tab=starred">Clear filters' in page
