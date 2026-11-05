import logging
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from prospector.companies.discover import scheduled_discover
from prospector.config import parse_hhmm
from prospector.context import AppContext
from prospector.expiry import check_links, run_expiry
from prospector.fx import fetch_rates
from prospector.notify.run import send_digest
from prospector.pipeline import nightly, tick

log = logging.getLogger(__name__)
TZ = ZoneInfo("Africa/Tunis")


def _guard(name, fn, ctx):
    def run():
        try:
            fn(ctx, datetime.now(UTC))
        except Exception:  # noqa: BLE001 — keep the scheduler alive
            log.exception("job %s failed", name)
    return run


def build_scheduler(ctx: AppContext) -> BackgroundScheduler:
    sched = BackgroundScheduler(timezone=TZ)
    once = {"max_instances": 1, "coalesce": True}
    at = parse_hhmm(ctx.settings.digest_time)
    sched.add_job(_guard("tick", tick, ctx), IntervalTrigger(minutes=15, timezone=TZ), id="tick",
                  next_run_time=datetime.now(TZ), **once)
    sched.add_job(_guard("digest", send_digest, ctx), CronTrigger(hour=at.hour, minute=at.minute, timezone=TZ), id="digest", **once)
    sched.add_job(_guard("nightly", nightly, ctx), CronTrigger(hour=3, minute=0, timezone=TZ), id="nightly", **once)
    # Expiry runs half an hour before the digest, so the digest never lists a lead that just expired.
    before = (datetime.combine(date(2000, 1, 2), at) - timedelta(minutes=30)).time()
    sched.add_job(_guard("expiry", run_expiry, ctx), CronTrigger(hour=before.hour, minute=before.minute, timezone=TZ),
                  id="expiry", **once)
    sched.add_job(_guard("links", check_links, ctx), CronTrigger(day_of_week="sun", hour=4, minute=0, timezone=TZ),
                  id="links", **once)
    sched.add_job(_guard("discover", scheduled_discover, ctx), CronTrigger(hour=4, minute=0, timezone=TZ),
                  id="discover", **once)
    # Rates once a day; also right away when today's are missing (first start, or the server was down at 03:30).
    now_if_missing = {} if ctx.fx.has_today() else {"next_run_time": datetime.now(TZ)}
    sched.add_job(_guard("fx", fetch_rates, ctx), CronTrigger(hour=3, minute=30, timezone=TZ), id="fx",
                  **now_if_missing, **once)
    return sched
