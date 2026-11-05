import logging
from datetime import datetime, timedelta

import httpx

from prospector.http import describe_error
from prospector.models import RawLead
from prospector.sources.base import Source
from prospector.store.health import HealthRepo, SourceHealth

log = logging.getLogger(__name__)
PAUSE_AFTER = 3
SCHEDULE_SLACK = timedelta(minutes=2)


def _missing_ratio(leads: list[RawLead]) -> float:
    missing = sum(1 for l in leads if not (l.title.strip() and l.url.strip() and l.body.strip()))
    return missing / len(leads)


def run_source(source: Source, http: httpx.Client, health: HealthRepo, now: datetime) -> list[RawLead]:
    """Fetch one source in isolation; failures are recorded, never raised."""
    try:
        leads = source.fetch(http)
    except Exception as e:  # noqa: BLE001 — any adapter failure must stay contained
        error = describe_error(e)
        log.warning("source %s failed: %s", source.id, error)
        st = health.record_failure(source.id, error)
        if st.consecutive_failures >= PAUSE_AFTER:
            health.set_paused(source.id, True)
        return []
    # Nothing back usually means the site changed, except for sources that are empty between rounds (GSoC).
    empty_ok = getattr(source, "may_be_empty", False)
    drift = (not leads and not empty_ok) or (bool(leads) and _missing_ratio(leads) > 0.5)
    health.record_success(source.id, len(leads), drift)
    return leads


def should_run(h: SourceHealth, source: Source, now: datetime) -> bool:
    if h.last_run is None:
        return True
    # last_run is stamped when the fetch ends, so allow for fetch duration / tick jitter.
    elapsed = now - datetime.fromisoformat(h.last_run) + SCHEDULE_SLACK
    if h.paused:
        return elapsed >= timedelta(hours=24)
    return elapsed >= timedelta(hours=source.interval_hours)
