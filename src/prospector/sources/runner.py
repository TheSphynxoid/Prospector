import logging
from datetime import datetime, timedelta

import httpx

from prospector.models import RawLead
from prospector.sources.base import Source
from prospector.store.health import HealthRepo, SourceHealth

log = logging.getLogger(__name__)
PAUSE_AFTER = 3


def _missing_ratio(leads: list[RawLead]) -> float:
    missing = sum(1 for l in leads if not (l.title.strip() and l.url.strip() and l.body.strip()))
    return missing / len(leads)


def run_source(source: Source, http: httpx.Client, health: HealthRepo, now: datetime) -> list[RawLead]:
    """Fetch one source in isolation; failures are recorded, never raised."""
    try:
        leads = source.fetch(http)
    except Exception as e:  # noqa: BLE001 — any adapter failure must stay contained
        log.warning("source %s failed: %s", source.id, e)
        st = health.record_failure(source.id, f"{type(e).__name__}: {e}")
        if st.consecutive_failures >= PAUSE_AFTER:
            health.set_paused(source.id, True)
        return []
    drift = not leads or _missing_ratio(leads) > 0.5
    health.record_success(source.id, len(leads), drift)
    return leads


def should_run(h: SourceHealth, source: Source, now: datetime) -> bool:
    if h.last_run is None:
        return True
    elapsed = now - datetime.fromisoformat(h.last_run)
    if h.paused:
        return elapsed >= timedelta(hours=24)
    return elapsed >= timedelta(hours=source.interval_hours)
