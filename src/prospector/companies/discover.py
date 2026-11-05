"""Find companies on Greenhouse, Lever and Ashby through `site:` searches on the owner's SearXNG.

Brave is the one engine that honours `site:` and the server's IP is shared, so a run is small and spaced
(16 searches, 20 s apart) and stops at the first sign of throttling. A throttled scheduled run also skips the
next day's run.
"""
import logging
import re
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from prospector.companies.boards import parse_board_url
from prospector.search.client import search, search_ready

log = logging.getLogger(__name__)
TZ = ZoneInfo("Africa/Tunis")
DOMAINS: tuple[str, ...] = ("jobs.lever.co", "boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.ashbyhq.com")
DISCOVER_GAP = 20  # seconds between searches
RUN_AT_HOUR = 4    # Tunis, the scheduled run
_PLAIN = re.compile(r"^[a-z0-9]+$")
STOP_AFTER_EMPTY = 2  # empty answers in a row; one can be honest ("golang intern" on one board)
_RUNNING = threading.Lock()  # one run at a time: two would double the rate seen from the shared IP


@dataclass
class DiscoverStats:
    searched: int = 0
    found: int = 0
    added: int = 0
    throttled: bool = False
    error: str | None = None


def _term(skill: str) -> str:
    s = skill.strip().lower()
    if s in ("go", "golang"):
        return "golang"
    return s if _PLAIN.match(s) else f'"{s}"'


def queries(profile) -> list[str]:
    ranked = sorted(profile.skills.items(), key=lambda kv: -kv[1])
    skills = [_term(name) for name, _ in ranked if name.strip()][:2]
    if not skills:
        return []
    terms = [*skills, f"{skills[0]} intern", f"{skills[0]} junior"]
    return [f"site:{domain} {term}" for domain in DOMAINS for term in terms]


def _backoff_until(now: datetime) -> datetime:
    """The day after next at 04:00 Tunis, so the next scheduled run is skipped."""
    day = now.astimezone(TZ).date() + timedelta(days=2)
    return datetime(day.year, day.month, day.day, RUN_AT_HOUR, tzinfo=TZ)


def is_running() -> bool:
    return _RUNNING.locked()


def discover(ctx, now: datetime, *, manual: bool = False, sleep=time.sleep) -> DiscoverStats:
    stats = DiscoverStats()
    if not search_ready(ctx):
        stats.error = "Web search is not set up"
        return stats
    if not _RUNNING.acquire(blocking=False):
        stats.error = "Discovery is already running"
        return stats
    try:
        _run(ctx, now, stats, sleep)
    finally:
        _RUNNING.release()
    ctx.kv.set("discover_last", {"at": now.isoformat(), "manual": manual, **asdict(stats)})
    return stats


def _run(ctx, now: datetime, stats: DiscoverStats, sleep) -> None:
    empty = 0
    for i, query in enumerate(queries(ctx.profile)):
        if i:
            sleep(DISCOVER_GAP)
        result = search(ctx, query, engines="brave")
        stats.searched += 1
        empty = 0 if result.results else empty + 1
        if result.throttled or result.error or empty >= STOP_AFTER_EMPTY:
            stats.throttled, stats.error = result.throttled, result.error
            ctx.kv.set("discover_backoff_until", _backoff_until(now).isoformat())
            log.info("discovery stopped at %r: throttled=%s error=%s empty=%d",
                     query, result.throttled, result.error, empty)
            return
        for hit in result.results:
            parsed = parse_board_url(hit.url)
            if parsed is None:
                continue
            stats.found += 1
            if ctx.companies.add(*parsed, found_by=query):
                stats.added += 1
    ctx.kv.set("discover_backoff_until", None)  # a clean run: the engine is fine again


def scheduled_discover(ctx, now: datetime) -> None:
    if not search_ready(ctx):
        return
    until = ctx.kv.get("discover_backoff_until")
    if until and now < datetime.fromisoformat(until):
        log.info("discovery skipped: search backed off until %s", until)
        return
    discover(ctx, now)
