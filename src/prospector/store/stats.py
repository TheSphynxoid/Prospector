"""Read-only numbers for the overview page."""
import json
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from prospector.store.kv import KV

TZ = ZoneInfo("Africa/Tunis")


@dataclass
class Overview:
    new_today: int
    new_week: int
    starred: int
    applied: int
    llm_used: int
    per_day: list[tuple[date, int]]  # oldest first, every day present
    by_source: list[tuple[str, int]]  # most first; filtered leads excluded
    by_kind: list[tuple[str, int]]


class StatsRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def overview(self, now: datetime, days: int = 14) -> Overview:
        today = now.astimezone(TZ).date()
        first = today - timedelta(days=days - 1)
        # Fetch a day of slack either side and bucket in Python: created_at is UTC, days are Tunis days.
        since = datetime.combine(first, datetime.min.time(), TZ).astimezone(UTC) - timedelta(days=1)
        rows = self.conn.execute(
            "SELECT created_at, kind, status, sources FROM leads WHERE created_at >= ?", (since.isoformat(),)
        ).fetchall()

        per_day: Counter[date] = Counter()
        by_source: Counter[str] = Counter()
        by_kind: Counter[str] = Counter()
        for r in rows:
            day = datetime.fromisoformat(r["created_at"]).astimezone(TZ).date()
            if day < first:
                continue
            per_day[day] += 1
            if r["status"] != "filtered":
                by_kind[r["kind"]] += 1
                for s in json.loads(r["sources"]):
                    by_source[s] += 1

        status = dict(self.conn.execute("SELECT status, COUNT(*) FROM leads GROUP BY status").fetchall())
        series = [(first + timedelta(days=i), per_day[first + timedelta(days=i)]) for i in range(days)]
        return Overview(
            new_today=per_day[today],
            new_week=sum(n for d, n in series if d > today - timedelta(days=7)),
            starred=status.get("starred", 0),
            applied=status.get("applied", 0),
            llm_used=KV(self.conn).get(f"llm_calls:{now.astimezone(UTC).date().isoformat()}", 0),
            per_day=series,
            by_source=_sorted(by_source),
            by_kind=_sorted(by_kind),
        )


def _sorted(c: Counter[str]) -> list[tuple[str, int]]:
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))
