from datetime import UTC, datetime, timedelta

import httpx
import pytest

from prospector.assist.fetch import page_gone
from prospector.models import RawLead, Status
from prospector.notify.digest import build_digest, render_email, render_telegram
from prospector.pipeline import ingest
from prospector.scheduler import build_scheduler
from tests.assist.test_fetch import Site, html, resolver
from tests.test_scheduler import make_ctx


@pytest.mark.parametrize("status, gone", [(404, True), (410, True), (200, False), (403, False), (500, False)])
def test_page_gone(status, gone):
    site = Site({"https://jobs.example/1": html("x", status=status)})
    assert page_gone("https://jobs.example/1", transport=httpx.MockTransport(site), resolve=resolver()) is gone


def test_page_gone_never_fetches_private(make_lead):
    site = Site({"https://jobs.example/1": html("x", status=404)})
    assert page_gone("https://jobs.example/1", transport=httpx.MockTransport(site), resolve=resolver("10.0.0.1")) is False
    assert site.seen == []


def test_expiry_jobs_scheduled_before_digest(tmp_path):
    ctx = make_ctx(tmp_path)
    sched = build_scheduler(ctx)
    t0 = datetime(2026, 11, 3, 5, 0, tzinfo=UTC)
    expiry = sched.get_job("expiry").trigger.get_next_fire_time(None, t0)
    assert expiry.astimezone(UTC) == datetime(2026, 11, 3, 6, 30, tzinfo=UTC)  # 07:30 Tunis, digest at 08:00
    links = sched.get_job("links").trigger.get_next_fire_time(None, t0)
    assert links.astimezone(UTC).weekday() == 6
    assert all(j.max_instances == 1 for j in sched.get_jobs())


def test_expiry_job_wraps_past_midnight(tmp_path):
    ctx = make_ctx(tmp_path)
    ctx.settings.digest_time = "00:10"
    nxt = build_scheduler(ctx).get_job("expiry").trigger.get_next_fire_time(None, datetime(2026, 11, 3, 5, tzinfo=UTC))
    assert nxt.astimezone(UTC) == datetime(2026, 11, 3, 22, 40, tzinfo=UTC)  # 23:40 Tunis


class OneShot:
    id = "freelancer"
    interval_hours = 3

    def fetch(self, http):
        return [RawLead(source_id="freelancer", external_id="555", url="https://www.freelancer.com/projects/x",
                        title="Go API", body="b", location_text="Remote", kind_hint=None, raw_payload="{}")]


def test_ingest_records_external_id(tmp_path):
    ctx = make_ctx(tmp_path)
    ingest(ctx, OneShot(), datetime.now(UTC))
    lid = ctx.leads.list(Status.NEW)[0].lead.id if ctx.leads.list(Status.NEW) else \
        ctx.conn.execute("SELECT id FROM leads").fetchone()["id"]
    assert ctx.expiry.refs("freelancer", [lid]) == {lid: "555"}


def test_digest_lists_maybe_closed(tmp_path, make_lead):
    ctx = make_ctx(tmp_path)
    lid = ctx.leads.insert(make_lead(title="Starred gig"))
    ctx.leads.set_status(lid, Status.STARRED)
    ctx.expiry.flag(lid, "freelancer", "Closed on Freelancer.")
    d = build_digest(ctx.leads, ctx.health, ctx.kv, datetime.now(UTC) + timedelta(minutes=1), "https://p", ctx.expiry)
    assert [r.lead.id for r in d.closed] == [lid]
    tg = "\n".join(render_telegram(d))
    assert "May have closed" in tg and "Closed on Freelancer." in tg and "Starred gig" in tg
    _, text, body = render_email(d)
    assert "Closed on Freelancer." in text and "May have closed" in body
