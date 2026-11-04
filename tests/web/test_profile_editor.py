from prospector.models import Status
from prospector.profile.model import Interest
from tests.web.test_settings_page import (as_form, env, example_profile, form_of, profile_form_of,  # noqa: F401
                                          saved, setup)


def test_profile_page_sections(example_profile):
    client, _, _ = example_profile
    page = client.get("/settings/profile").text
    for h in ("About you", "Skills", "Projects", "What you want", "Filters", "Interests", "CVs", "Edit as YAML"):
        assert f">{h}<" in page, h


def test_skill_weight_steps(example_profile, ctx):
    client, _, _ = example_profile
    ctx.profile = ctx.profile.model_copy(update={"skills": {"go": 1.0, "c": 0.7, "sql": 0.4, "odd": 0.55}})
    page = client.get("/settings/profile").text
    assert '<option value="1" selected>Core</option>' in page
    assert '<option value="0.55" selected>Custom (0.55)</option>' in page
    client.post("/settings/profile", data=as_form(profile_form_of(client)))
    assert ctx.profile.skills == {"go": 1.0, "c": 0.7, "sql": 0.4, "odd": 0.55}


def test_about_saved_from_form(example_profile, ctx):
    client, _, _ = example_profile
    pairs = [p for p in profile_form_of(client) if not p[0].startswith("about")]
    pairs += [("about_present", "1"), ("about[name]", "Hamza"), ("about[headline]", "C++/Go engineer"),
              ("about[highlights]", "Built a room-mapping engine\n\nShipped a scraper"),
              ("about_lang[0][language]", "Arabic"), ("about_lang[0][level]", "native"),
              ("education[0][school]", "ENIT"), ("education[0][year]", "2027"),
              ("availability[hours_per_week]", "30"), ("availability[open_to]", "gigs"),
              ("availability[open_to]", "internship"), ("links[github]", "https://github.com/x")]
    r = client.post("/settings/profile", data=as_form(pairs))
    a = ctx.profile.about
    assert r.status_code == 200 and a.name == "Hamza" and a.highlights == ["Built a room-mapping engine", "Shipped a scraper"]
    assert a.languages[0].level == "native" and a.education[0].year == 2027
    assert a.availability.open_to == ["gigs", "internship"] and a.links.github == "https://github.com/x"


def test_interest_preview_route(example_profile, ctx, make_lead):
    client, _, _ = example_profile
    ctx.leads.insert(make_lead(canonical_url="a", title="Rust backend"))
    r = client.get("/settings/profile/interest-preview", params={"boost[3][keyword]": "rust", "boost[3][where]": "title"})
    assert "Matches 1 of your current leads" in r.text and "Rust backend" in r.text
    assert "Matches" not in client.get("/settings/profile/interest-preview", params={"boost[0][keyword]": ""}).text


def test_suggestions_route(example_profile, ctx, make_lead):
    client, _, _ = example_profile
    for i in range(2):
        lid = ctx.leads.insert(make_lead(canonical_url=f"s{i}", title=f"Embedded Linux engineer {i}"))
        ctx.leads.set_status(lid, Status.STARRED)
    r = client.get("/settings/profile/suggestions")
    assert "embedded linux" in r.text


def test_yaml_save_route(example_profile, ctx):
    client, restarts, _ = example_profile
    from prospector.profile.yaml_io import dump
    before = ctx.profile
    r = client.post("/settings/profile/yaml", data={"yaml": "skills:\n  go: 1\nprojects: []\n  bad: x\n"})
    assert r.status_code == 400 and "line 4" in r.text and ctx.profile == before
    text = dump(before.model_copy(update={"interests": [Interest(phrase="zig", weight=0.5)]}))
    r = client.post("/settings/profile/yaml", data={"yaml": text})
    assert r.status_code == 200 and restarts == [] and ctx.profile.interests == [Interest(phrase="zig", weight=0.5)]


def test_regions_comma_text_saves(example_profile, ctx):
    client, _, _ = example_profile
    pairs = [(k, "EU, MENA ,  Remote" if k == "regions" else v) for k, v in profile_form_of(client)]
    client.post("/settings/profile", data=as_form(pairs))
    assert ctx.profile.targets.regions == ["EU", "MENA", "Remote"]
