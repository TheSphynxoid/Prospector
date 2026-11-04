"""Applications sent (from a lead or added by hand) and their timeline."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import Literal

from prospector.store.db import now_iso

Stage = Literal["waiting", "interview", "won", "rejected", "no_reply", "withdrawn"]
STAGES: tuple[str, ...] = ("waiting", "interview", "won", "rejected", "no_reply", "withdrawn")
OPEN_STAGES: tuple[str, ...] = ("waiting", "interview")
CLOSED_STAGES: tuple[str, ...] = ("rejected", "no_reply", "withdrawn")
_FIELDS = ("lead_id", "title", "client", "source", "kind", "url", "applied_on", "stage", "follow_up_on",
           "follow_ups", "next_step", "closed_on", "notes", "from_lead_action")
_DATES = ("applied_on", "follow_up_on", "closed_on")


@dataclass
class Application:
    id: int
    lead_id: int | None
    title: str
    client: str | None
    source: str | None
    kind: str | None
    url: str | None
    applied_on: date
    stage: str
    follow_up_on: date | None
    follow_ups: int
    next_step: str | None
    closed_on: date | None
    notes: str
    from_lead_action: bool

    @property
    def is_open(self) -> bool:
        return self.stage in OPEN_STAGES


@dataclass
class AppEvent:
    id: int
    at: str
    kind: str  # applied | followed_up | stage | note | snoozed
    text: str


def _db(field: str, value):
    if field in _DATES and isinstance(value, date):
        return value.isoformat()
    if field == "from_lead_action":
        return int(bool(value))
    return value


def _row(r: sqlite3.Row) -> Application:
    d = {f: r[f] for f in _FIELDS}
    for f in _DATES:
        d[f] = date.fromisoformat(d[f]) if d[f] else None
    d["from_lead_action"] = bool(d["from_lead_action"])
    return Application(id=r["id"], **d)


class ApplicationRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(self, **fields) -> int:
        bad = set(fields) - set(_FIELDS)
        if bad:
            raise TypeError(f"unknown fields {sorted(bad)}")
        fields.setdefault("stage", "waiting")
        now = now_iso()
        cols = list(fields)
        cur = self.conn.execute(
            f"INSERT INTO applications({', '.join(cols)}, created_at, updated_at) "
            f"VALUES ({', '.join('?' * len(cols))}, ?, ?)",
            (*(_db(c, fields[c]) for c in cols), now, now))
        aid = cur.lastrowid
        self.add_event(aid, "applied")
        return aid

    def get(self, id: int) -> Application | None:
        r = self.conn.execute("SELECT * FROM applications WHERE id = ?", (id,)).fetchone()
        return _row(r) if r else None

    def by_lead(self, lead_id: int) -> Application | None:
        r = self.conn.execute("SELECT * FROM applications WHERE lead_id = ?", (lead_id,)).fetchone()
        return _row(r) if r else None

    def list(self, stage: str | None = None, source: str | None = None, limit: int = 50, offset: int = 0,
             stages: tuple[str, ...] | None = None) -> list[Application]:
        where, args = [], []
        if stage:
            where.append("stage = ?"), args.append(stage)
        if stages:
            where.append(f"stage IN ({', '.join('?' * len(stages))})"), args.extend(stages)
        if source:
            where.append("source = ?"), args.append(source)
        sql = "SELECT * FROM applications" + (f" WHERE {' AND '.join(where)}" if where else "")
        sql += " ORDER BY applied_on DESC, id DESC LIMIT ? OFFSET ?"
        return [_row(r) for r in self.conn.execute(sql, (*args, limit, offset))]

    def update(self, id: int, **fields) -> None:
        bad = set(fields) - set(_FIELDS)
        if bad:
            raise TypeError(f"unknown fields {sorted(bad)}")
        if not fields:
            return
        sets = ", ".join(f"{f} = ?" for f in fields)
        self.conn.execute(f"UPDATE applications SET {sets}, updated_at = ? WHERE id = ?",
                          (*(_db(f, v) for f, v in fields.items()), now_iso(), id))

    def add_event(self, id: int, kind: str, text: str = "") -> None:
        self.conn.execute("INSERT INTO app_events(application_id, at, kind, text) VALUES (?,?,?,?)",
                          (id, now_iso(), kind, text))

    def events(self, id: int) -> list[AppEvent]:
        rows = self.conn.execute("SELECT * FROM app_events WHERE application_id = ? ORDER BY id", (id,))
        return [AppEvent(r["id"], r["at"], r["kind"], r["text"]) for r in rows]

    def delete(self, id: int) -> None:
        self.conn.execute("DELETE FROM app_events WHERE application_id = ?", (id,))
        self.conn.execute("DELETE FROM applications WHERE id = ?", (id,))

    def counts_since(self, day: date) -> dict[str, int]:
        """Sent since `day`; of those, how many got any answer (anything but waiting/no reply) and how many won."""
        r = self.conn.execute(
            "SELECT COUNT(*) AS sent, "
            "SUM(stage NOT IN ('waiting', 'no_reply', 'withdrawn')) AS replied, SUM(stage = 'won') AS won "
            "FROM applications WHERE applied_on >= ?", (day.isoformat(),)).fetchone()
        return {"sent": r["sent"], "replied": r["replied"] or 0, "won": r["won"] or 0}

    def sources(self) -> list[str]:
        return [r["source"] for r in self.conn.execute(
            "SELECT DISTINCT source FROM applications WHERE source IS NOT NULL AND source != '' ORDER BY source")]

    def stage_counts(self) -> dict[str, int]:
        return {r["stage"]: r["n"] for r in self.conn.execute(
            "SELECT stage, COUNT(*) AS n FROM applications GROUP BY stage")}
