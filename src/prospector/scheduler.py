import logging
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from prospector.context import AppContext
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
    sched.add_job(_guard("tick", tick, ctx), IntervalTrigger(minutes=15, timezone=TZ), id="tick",
                  next_run_time=datetime.now(TZ), **once)
    sched.add_job(_guard("digest", send_digest, ctx), CronTrigger(hour=8, minute=0, timezone=TZ), id="digest", **once)
    sched.add_job(_guard("nightly", nightly, ctx), CronTrigger(hour=3, minute=0, timezone=TZ), id="nightly", **once)
    return sched
