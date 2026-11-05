from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from prospector.store.db import now_iso

STATES = ("watching", "muted", "paused")
RECHECK = timedelta(hours=24)
PAUSE_AFTER = 3  # errors in a row


@dataclass
class Company:
    id: int
    board: str
    token: str
    name: str | None
    state: str
    found_by: str | None
    added_at: str
    last_checked: datetime | None
    last_count: int | None
    last_error: str | None
    failures: int

    @property
    def display_name(self) -> str:
        return self.name or self.token.replace("-", " ").replace("_", " ").replace(".", " ").title()


def _company(row) -> Company:
    d = dict(row)
    lc = d["last_checked"]
    if lc:
        dt = datetime.fromisoformat(lc)
        d["last_checked"] = dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    return Company(**d)


_ORDER = ("ORDER BY CASE state WHEN 'watching' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END, "
          "COALESCE(last_count, -1) DESC, LOWER(COALESCE(name, token))")


class CompanyRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, board: str, token: str, found_by: str | None = None, name: str | None = None) -> bool:
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO companies(board, token, name, found_by, added_at) VALUES (?,?,?,?,?)",
            (board, token, name, found_by, now_iso()))
        return cur.rowcount == 1

    def get(self, id: int) -> Company | None:
        row = self.conn.execute("SELECT * FROM companies WHERE id = ?", (id,)).fetchone()
        return _company(row) if row else None

    def list(self, state: str | None = None) -> list[Company]:
        if state:
            rows = self.conn.execute(f"SELECT * FROM companies WHERE state = ? {_ORDER}", (state,))
        else:
            rows = self.conn.execute(f"SELECT * FROM companies {_ORDER}")
        return [_company(r) for r in rows.fetchall()]

    def due(self, now: datetime, limit: int) -> list[Company]:
        """Watched companies not checked in the last 24 h, never-checked first, then oldest."""
        cutoff = now - RECHECK
        rows = self.conn.execute(
            "SELECT * FROM companies WHERE state = 'watching' ORDER BY last_checked IS NOT NULL, last_checked, id"
        ).fetchall()
        out = []
        for c in map(_company, rows):
            if c.last_checked is None or c.last_checked <= cutoff:
                out.append(c)
                if len(out) >= limit:
                    break
        return out

    def record_ok(self, id: int, count: int, name: str | None) -> None:
        self.conn.execute(
            "UPDATE companies SET last_checked=?, last_count=?, name=COALESCE(?, name), last_error=NULL, "
            "failures=0 WHERE id=?", (now_iso(), count, name or None, id))

    def record_error(self, id: int, error: str) -> None:
        self.conn.execute(
            "UPDATE companies SET last_checked=?, last_error=?, failures=failures+1, "
            "state=CASE WHEN failures+1 >= ? AND state='watching' THEN 'paused' ELSE state END WHERE id=?",
            (now_iso(), error[:300], PAUSE_AFTER, id))

    def set_state(self, id: int, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        if state == "watching":
            self.conn.execute("UPDATE companies SET state='watching', failures=0 WHERE id=?", (id,))
        else:
            self.conn.execute("UPDATE companies SET state=? WHERE id=?", (state, id))

    def counts(self) -> dict[str, int]:
        out = dict.fromkeys(STATES, 0)
        for state, n in self.conn.execute("SELECT state, COUNT(*) FROM companies GROUP BY state").fetchall():
            out[state] = n
        return out
