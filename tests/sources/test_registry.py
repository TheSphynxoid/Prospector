from prospector.config import Settings
from prospector.sources.registry import FACTORIES, build_sources, register
from prospector.store.db import connect
from prospector.store.mail import MailRepo


def settings(**kw):
    base = dict(llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a", profile_path="p")
    base.update(kw)
    return Settings(_env_file=None, **base)


def test_build_sources_enabled_only_and_skips_missing_credentials(monkeypatch):
    class S:
        def __init__(self, sid):
            self.id, self.interval_hours = sid, 1

        def fetch(self, http):
            return []

    monkeypatch.setattr("prospector.sources.registry.FACTORIES", {})
    register("a")(lambda s, m: S("a"))
    register("b")(lambda s, m: None)
    register("c")(lambda s, m: S("c"))
    from prospector.sources import registry
    assert registry.FACTORIES is not FACTORIES
    out = build_sources(settings(enabled_sources=["a", "b", "zzz"]), MailRepo(connect(":memory:")))
    assert [s.id for s in out] == ["a"]
