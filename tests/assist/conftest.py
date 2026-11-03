import json

import httpx
import pytest

from prospector.config import Settings
from prospector.context import AppContext
from prospector.llm.client import LLMError
from prospector.models import Kind
from prospector.profile.model import Profile, Project, Targets
from prospector.store.db import connect


class FakeLLM:
    """Stands in for LLMClient.chat: records calls, returns (or raises) queued replies."""
    model = "fake"

    def __init__(self):
        self.replies: list = []
        self.calls: list[dict] = []

    def chat(self, system, messages, session_id, temperature=0.4):
        self.calls.append({"system": system, "messages": list(messages), "session_id": session_id})
        r = self.replies.pop(0) if self.replies else "ok"
        if isinstance(r, Exception):
            raise r
        return r if isinstance(r, str) else json.dumps(r)


@pytest.fixture
def fake():
    return FakeLLM()


@pytest.fixture
def actx(tmp_path, fake):
    s = Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p.yaml", data_dir=tmp_path)
    prof = Profile(skills={"go": 1}, projects=[Project(name="Room-mapping engine", writeup="Hotel rooms.")],
                   targets=Targets(kinds=list(Kind), regions=[]))
    return AppContext.create(s, connect(":memory:"), prof, httpx.Client(), assistant_llm=fake)


@pytest.fixture
def lid(actx, make_lead):
    return actx.leads.insert(make_lead(title="Go API", body="Build a Go API."))


__all__ = ["FakeLLM", "LLMError"]
