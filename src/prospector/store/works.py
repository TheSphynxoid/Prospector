"""Won work and its payments. A received payment keeps the exchange rates of the day it arrived."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING, Literal

from prospector.fx import CURRENCIES
from prospector.store.db import now_iso

if TYPE_CHECKING:
    from prospector.fx import Rates

WorkStage = Literal["in_progress", "delivered", "closed", "cancelled"]
WORK_STAGES: tuple[str, ...] = ("in_progress", "delivered", "closed", "cancelled")
ACTIVE_STAGES: tuple[str, ...] = ("in_progress", "delivered")
_FIELDS = ("application_id", "lead_id", "title", "client", "kind", "price_milli", "currency", "stage",
           "started_on", "ended_on", "notes")
_DATES = ("started_on", "ended_on")


@dataclass
class Work:
    id: int
    application_id: int | None
    lead_id: int | None
    title: str
    client: str | None
    kind: str | None
    price_milli: int | None
    currency: str
    stage: str
    started_on: date
    ended_on: date | None
    notes: str


@dataclass
class Payment:
    id: int
    work_id: int
    amount_milli: int
    currency: str
    status: str  # expected | received
    due_on: date | None
    received_on: date | None
    account_id: int | None
    usd_rate: float | None
    usd_milli: int | None
    account_milli: int | None
    note: str


def _d(v):
    return date.fromisoformat(v) if v else None


def _work(r) -> Work:
    d = {f: r[f] for f in _FIELDS}
    for f in _DATES:
        d[f] = _d(d[f])
    return Work(id=r["id"], **d)


def _payment(r) -> Payment:
    return Payment(r["id"], r["work_id"], r["amount_milli"], r["currency"], r["status"], _d(r["due_on"]),
                   _d(r["received_on"]), r["account_id"], r["usd_rate"], r["usd_milli"], r["account_milli"], r["note"])


def _db(f, v):
    return v.isoformat() if f in _DATES and isinstance(v, date) else v


def _check_currency(code: str) -> None:
    if code not in CURRENCIES:
        raise ValueError(f"Pick one of {', '.join(CURRENCIES)}.")


class WorkRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    # work items

    def create(self, **fields) -> int:
        bad = set(fields) - set(_FIELDS)
        if bad:
            raise TypeError(f"unknown fields {sorted(bad)}")
        fields.setdefault("currency", "USD")
        fields.setdefault("stage", "in_progress")
        _check_currency(fields["currency"])
        cols, now = list(fields), now_iso()
        return self.conn.execute(
            f"INSERT INTO works({', '.join(cols)}, created_at, updated_at) VALUES ({', '.join('?' * len(cols))}, ?, ?)",
            (*(_db(c, fields[c]) for c in cols), now, now)).lastrowid

    def get(self, id: int) -> Work | None:
        r = self.conn.execute("SELECT * FROM works WHERE id = ?", (id,)).fetchone()
        return _work(r) if r else None

    def by_application(self, app_id: int) -> Work | None:
        r = self.conn.execute("SELECT * FROM works WHERE application_id = ?", (app_id,)).fetchone()
        return _work(r) if r else None

    def list(self, stage: str | None = None, stages: tuple[str, ...] | None = None, limit: int = 50,
             offset: int = 0) -> list[Work]:
        where, args = [], []
        if stage:
            where.append("stage = ?"), args.append(stage)
        if stages:
            where.append(f"stage IN ({', '.join('?' * len(stages))})"), args.extend(stages)
        sql = "SELECT * FROM works" + (f" WHERE {' AND '.join(where)}" if where else "")
        return [_work(r) for r in self.conn.execute(sql + " ORDER BY started_on DESC, id DESC LIMIT ? OFFSET ?",
                                                    (*args, limit, offset))]

    def update(self, id: int, **fields) -> None:
        bad = set(fields) - set(_FIELDS)
        if bad:
            raise TypeError(f"unknown fields {sorted(bad)}")
        if "currency" in fields:
            _check_currency(fields["currency"])
        if fields:
            sets = ", ".join(f"{f} = ?" for f in fields)
            self.conn.execute(f"UPDATE works SET {sets}, updated_at = ? WHERE id = ?",
                              (*(_db(f, v) for f, v in fields.items()), now_iso(), id))

    def stage_counts(self) -> dict[str, int]:
        return {r["stage"]: r["n"] for r in self.conn.execute("SELECT stage, COUNT(*) AS n FROM works GROUP BY stage")}

    # payments

    def add_expected(self, work_id: int, amount_milli: int, currency: str, due_on: date | None, note: str = "") -> int:
        _check_currency(currency)
        return self.conn.execute(
            "INSERT INTO payments(work_id, amount_milli, currency, status, due_on, note, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (work_id, amount_milli, currency, "expected", _db("started_on", due_on), note, now_iso())).lastrowid

    def receive(self, payment_id: int, on: date, account_id: int, rates: Rates) -> None:
        """Mark received; the USD value and the amount in the account's currency are fixed at that day's rates."""
        p = self.payment(payment_id)
        acc = self.conn.execute("SELECT currency FROM accounts WHERE id = ?", (account_id,)).fetchone()
        if p is None or acc is None:
            raise LookupError("payment or account not found")
        self.conn.execute(
            "UPDATE payments SET status = 'received', received_on = ?, account_id = ?, usd_rate = ?, usd_milli = ?, "
            "account_milli = ? WHERE id = ?",
            (on.isoformat(), account_id, rates.rate(p.currency, on), rates.convert(p.amount_milli, p.currency, "USD", on),
             rates.convert(p.amount_milli, p.currency, acc["currency"], on), payment_id))

    def add_received(self, work_id: int, amount_milli: int, currency: str, on: date, account_id: int, rates: Rates,
                     note: str = "") -> int:
        pid = self.add_expected(work_id, amount_milli, currency, None, note)
        self.receive(pid, on, account_id, rates)
        return pid

    def payment(self, id: int) -> Payment | None:
        r = self.conn.execute("SELECT * FROM payments WHERE id = ?", (id,)).fetchone()
        return _payment(r) if r else None

    def delete_payment(self, id: int) -> None:
        self.conn.execute("DELETE FROM payments WHERE id = ?", (id,))

    def payments(self, work_id: int) -> list[Payment]:
        return [_payment(r) for r in self.conn.execute(
            "SELECT * FROM payments WHERE work_id = ? ORDER BY COALESCE(received_on, due_on, created_at), id", (work_id,))]

    def paid_usd_milli(self, work_id: int) -> int:
        r = self.conn.execute("SELECT SUM(usd_milli) AS s FROM payments WHERE work_id = ? AND status = 'received'",
                              (work_id,)).fetchone()
        return r["s"] or 0

    def received_between(self, start: date, end: date) -> list[Payment]:
        """Received payments with start <= received_on <= end, newest first."""
        return [_payment(r) for r in self.conn.execute(
            "SELECT * FROM payments WHERE status = 'received' AND received_on BETWEEN ? AND ? "
            "ORDER BY received_on DESC, id DESC", (start.isoformat(), end.isoformat()))]

    def expected(self, limit: int | None = None) -> list[Payment]:
        sql = "SELECT * FROM payments WHERE status = 'expected' ORDER BY due_on IS NULL, due_on, id"
        return [_payment(r) for r in self.conn.execute(sql + (f" LIMIT {int(limit)}" if limit else ""))]
