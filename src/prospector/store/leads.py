from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from prospector.models import Kind, Lead, Pay, Remote, Status, company_norm
from prospector.store.db import now_iso


@dataclass
class LeadRow:
    lead: Lead
    stage1: float | None
    stage2: dict | None


def _lead(row: sqlite3.Row) -> Lead:
    pay = json.loads(row["pay"]) if row["pay"] else None
    return Lead(
        id=row["id"],
        canonical_url=row["canonical_url"],
        title=row["title"],
        company=row["company"],
        kind=Kind(row["kind"]),
        remote=Remote(row["remote"]),
        remote_region=row["remote_region"],
        locations=json.loads(row["locations"]),
        pay=Pay(**pay) if pay else None,
        languages=json.loads(row["languages"]),
        deadline=date.fromisoformat(row["deadline"]) if row["deadline"] else None,
        posted_at=datetime.fromisoformat(row["posted_at"]) if row["posted_at"] else None,
        body=row["body"],
        content_hash=row["content_hash"],
        sources=json.loads(row["sources"]),
        status=Status(row["status"]),
        filter_reason=row["filter_reason"],
    )


def _row(row: sqlite3.Row) -> LeadRow:
    return LeadRow(
        lead=_lead(row),
        stage1=row["stage1"],
        stage2=json.loads(row["stage2"]) if row["stage2"] else None,
    )


_SELECT = "SELECT l.*, s.stage1, s.stage2 FROM leads l LEFT JOIN scores s ON s.lead_id = l.id"


class LeadRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, lead: Lead) -> int:
        cur = self.conn.execute(
            """INSERT INTO leads(canonical_url, title, company, company_norm, kind, remote, remote_region,
               locations, pay, languages, deadline, posted_at, body, content_hash, sources, status,
               filter_reason, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) RETURNING id""",
            (
                lead.canonical_url, lead.title, lead.company, company_norm(lead.company),
                lead.kind.value, lead.remote.value, lead.remote_region,
                json.dumps(lead.locations), json.dumps(asdict(lead.pay)) if lead.pay else None,
                json.dumps(lead.languages), lead.deadline.isoformat() if lead.deadline else None,
                lead.posted_at.isoformat() if lead.posted_at else None, lead.body,
                lead.content_hash, json.dumps(lead.sources), lead.status.value,
                lead.filter_reason, now_iso(),
            ),
        )
        # RETURNING, not lastrowid: lastrowid is per-connection and races across threads
        lead.id = cur.fetchone()[0]
        return lead.id

    def get(self, id: int) -> Lead | None:
        row = self.conn.execute("SELECT * FROM leads WHERE id = ?", (id,)).fetchone()
        return _lead(row) if row else None

    def get_row(self, id: int) -> LeadRow | None:
        row = self.conn.execute(f"{_SELECT} WHERE l.id = ?", (id,)).fetchone()
        return _row(row) if row else None

    def by_canonical_url(self, url: str) -> Lead | None:
        row = self.conn.execute("SELECT * FROM leads WHERE canonical_url = ?", (url,)).fetchone()
        return _lead(row) if row else None

    def recent_by_company(self, company_norm: str, days: int = 60) -> list[Lead]:
        if not company_norm:
            return []
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT * FROM leads WHERE company_norm = ? AND created_at >= ? ORDER BY id",
            (company_norm, since),
        ).fetchall()
        return [_lead(r) for r in rows]

    def add_source(self, id: int, source_id: str) -> None:
        lead = self.get(id)
        if lead and source_id not in lead.sources:
            self.conn.execute("UPDATE leads SET sources = ? WHERE id = ?",
                              (json.dumps(lead.sources + [source_id]), id))

    def set_status(self, id: int, status: Status, reason: str | None = None) -> None:
        self.conn.execute("UPDATE leads SET status = ?, filter_reason = ? WHERE id = ?",
                          (status.value, reason, id))

    def list(self, tab: Status, kind: Kind | None = None, remote: Remote | None = None,
             source: str | None = None, min_score: float | None = None,
             sort: Literal["score", "date"] = "score", limit: int = 50, offset: int = 0,
             q: str | None = None) -> list[LeadRow]:
        where, args = ["l.status = ?"], [tab.value]
        if q and q.strip():
            like = "%" + "".join("!" + c if c in "!%_" else c for c in q.strip()) + "%"  # ! escapes LIKE wildcards
            where.append("(l.title LIKE ? ESCAPE '!' OR l.company LIKE ? ESCAPE '!')")
            args += [like, like]
        if kind:
            where.append("l.kind = ?")
            args.append(kind.value)
        if remote:
            where.append("l.remote = ?")
            args.append(remote.value)
        if source:
            where.append("EXISTS (SELECT 1 FROM json_each(l.sources) WHERE value = ?)")
            args.append(source)
        if min_score is not None:
            where.append("s.stage1 >= ?")
            args.append(min_score)
        order = "COALESCE(s.stage1, -1) DESC, l.id DESC" if sort == "score" else "l.id DESC"
        rows = self.conn.execute(
            f"{_SELECT} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?",
            (*args, limit, offset),
        ).fetchall()
        return [_row(r) for r in rows]

    def new_since(self, ts: datetime, limit: int) -> list[LeadRow]:
        rows = self.conn.execute(
            f"{_SELECT} WHERE l.status = 'new' AND l.created_at >= ? "
            "ORDER BY COALESCE(s.stage1, -1) DESC LIMIT ?",
            (ts.astimezone(UTC).isoformat(), limit),
        ).fetchall()
        return [_row(r) for r in rows]

    def starred_with_deadline_within(self, days: int, today: date) -> list[LeadRow]:
        rows = self.conn.execute(
            f"{_SELECT} WHERE l.status = 'starred' AND l.deadline IS NOT NULL "
            "AND l.deadline >= ? AND l.deadline <= ? ORDER BY l.deadline",
            (today.isoformat(), (today + timedelta(days=days)).isoformat()),
        ).fetchall()
        return [_row(r) for r in rows]

    def put_raw(self, lead_id: int, source_id: str, raw_payload: str) -> None:
        self.conn.execute("INSERT INTO raw_payloads(lead_id, source_id, payload) VALUES (?,?,?)",
                          (lead_id, source_id, raw_payload))

    def prune_raw(self, older_than_days: int) -> int:
        cur = self.conn.execute("DELETE FROM raw_payloads WHERE stored_at < datetime('now', ?)",
                                (f"-{older_than_days} days",))
        return cur.rowcount
