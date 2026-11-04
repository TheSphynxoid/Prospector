from datetime import UTC, datetime

import httpx

from prospector.config import Settings
from prospector.context import AppContext
from prospector.models import Kind
from prospector.profile.model import Profile, Targets
from prospector.scheduler import build_scheduler
from prospector.store.db import connect


def make_ctx(tmp_path):
    s = Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain="t", access_aud="a",
                 profile_path=tmp_path / "p", data_dir=tmp_path)
    prof = Profile(skills={}, projects=[], targets=Targets(kinds=list(Kind), regions=[]))
    return AppContext.create(s, connect(":memory:"), prof, httpx.Client())


def test_digest_job_runs_at_8_tunis(tmp_path):
    sched = build_scheduler(make_ctx(tmp_path))
    trigger = sched.get_job("digest").trigger
    nxt = trigger.get_next_fire_time(None, datetime(2026, 11, 3, 6, 0, tzinfo=UTC))
    assert nxt.astimezone(UTC) == datetime(2026, 11, 3, 7, 0, tzinfo=UTC)


def test_jobs_registered_single_instance(tmp_path):
    sched = build_scheduler(make_ctx(tmp_path))
    assert {j.id for j in sched.get_jobs()} == {"tick", "digest", "nightly", "expiry", "links", "fx"}
    assert all(j.max_instances == 1 and j.coalesce for j in sched.get_jobs())
    nightly = sched.get_job("nightly").trigger.get_next_fire_time(None, datetime(2026, 11, 3, 6, 0, tzinfo=UTC))
    assert nightly.astimezone(UTC) == datetime(2026, 11, 4, 2, 0, tzinfo=UTC)


def test_digest_job_uses_setting(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.settings.digest_time = "19:30"
    trigger = build_scheduler(ctx).get_job("digest").trigger
    nxt = trigger.get_next_fire_time(None, datetime(2026, 11, 3, 6, 0, tzinfo=UTC))
    assert nxt.astimezone(UTC) == datetime(2026, 11, 3, 18, 30, tzinfo=UTC)  # 19:30 Tunis


def test_fx_job_daily_at_0330_tunis(tmp_path):
    sched = build_scheduler(make_ctx(tmp_path))
    nxt = sched.get_job("fx").trigger.get_next_fire_time(None, datetime(2026, 11, 3, 6, 0, tzinfo=UTC))
    assert nxt.astimezone(UTC) == datetime(2026, 11, 4, 2, 30, tzinfo=UTC)
