from tests.web.test_settings_page import (as_form, env, example_profile, form_of, profile_form_of,  # noqa: F401
                                          saved, setup)


def test_profile_save_reloads_without_restart(example_profile, ctx):
    client, restarts, _ = example_profile
    from tests.rank.test_stage1 import FakeEmbedder
    queued = []
    ctx.embedder, ctx.run_background = FakeEmbedder(), queued.append
    pairs = [(k, "Rust" if k == "skills[0][name]" else v) for k, v in profile_form_of(client)]
    r = client.post("/settings/profile", data=as_form(pairs))
    assert r.status_code == 200 and restarts == [] and "Rust" in ctx.profile.skills
    assert len(queued) == 1 and "Re-scoring" in r.text and ctx.profile_vecs is None


def test_profile_save_keeps_about(example_profile, ctx):
    client, _, _ = example_profile
    from prospector.profile.model import About
    ctx.profile = ctx.profile.model_copy(update={"about": About(name="Hamza")})
    client.post("/settings/profile", data=as_form(profile_form_of(client)))
    assert ctx.profile.about.name == "Hamza"


def test_profile_save_during_rescore(example_profile, ctx):
    client, _, _ = example_profile
    from tests.rank.test_stage1 import FakeEmbedder
    queued = []
    ctx.embedder, ctx.run_background = FakeEmbedder(), queued.append
    ctx.kv.set("rescore_status", {"state": "running", "count": 12})
    ctx.rescoring = True  # a job of this process is running
    r = client.post("/settings/profile", data=as_form(profile_form_of(client)))
    assert queued == [] and "Re-scoring 12 leads" in r.text
