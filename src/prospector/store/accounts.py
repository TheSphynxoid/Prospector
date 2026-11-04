"""Where money sits: Freelancer balance, Payoneer, a bank. Archived, never deleted, so history stays."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from prospector.fx import CURRENCIES
from prospector.store.db import now_iso

if TYPE_CHECKING:
    from prospector.fx import Rates


@dataclass
class Account:
    id: int
    name: str
    currency: str
    archived: bool


def _row(r) -> Account:
    return Account(r["id"], r["name"], r["currency"], bool(r["archived"]))


class AccountRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(self, name: str, currency: str) -> int:
        name = (name or "").strip()
        if not name:
            raise ValueError("Give the account a name.")
        if currency not in CURRENCIES:
            raise ValueError(f"Pick one of {', '.join(CURRENCIES)}.")
        try:
            return self.conn.execute("INSERT INTO accounts(name, currency, created_at) VALUES (?,?,?)",
                                     (name, currency, now_iso())).lastrowid
        except sqlite3.IntegrityError:
            raise ValueError("An account with that name already exists.") from None

    def get(self, id: int) -> Account | None:
        r = self.conn.execute("SELECT * FROM accounts WHERE id = ?", (id,)).fetchone()
        return _row(r) if r else None

    def list(self, include_archived: bool = False) -> list[Account]:
        sql = "SELECT * FROM accounts" + ("" if include_archived else " WHERE archived = 0") + " ORDER BY name"
        return [_row(r) for r in self.conn.execute(sql)]

    def archive(self, id: int) -> None:
        self.conn.execute("UPDATE accounts SET archived = 1 WHERE id = ?", (id,))

    def last_used(self) -> Account | None:
        r = self.conn.execute(
            "SELECT a.* FROM payments p JOIN accounts a ON a.id = p.account_id "
            "WHERE p.status = 'received' AND a.archived = 0 ORDER BY p.received_on DESC, p.id DESC LIMIT 1").fetchone()
        return _row(r) if r else None

    def add_transfer(self, on: date, from_id: int, to_id: int, sent_milli: int, received_milli: int,
                     note: str = "") -> int:
        if from_id == to_id:
            raise ValueError("Pick two different accounts.")
        if sent_milli <= 0 or received_milli <= 0:
            raise ValueError("Amounts must be above zero.")
        if self.get(from_id) is None or self.get(to_id) is None:
            raise ValueError("Pick existing accounts.")
        return self.conn.execute(
            "INSERT INTO transfers(on_day, from_account, to_account, sent_milli, received_milli, note, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (on.isoformat(), from_id, to_id, sent_milli, received_milli, note, now_iso())).lastrowid

    def transfers(self, start: date | None = None, end: date | None = None,
                  account_id: int | None = None) -> list[Transfer]:
        where, args = [], []
        if start:
            where.append("on_day >= ?"), args.append(start.isoformat())
        if end:
            where.append("on_day <= ?"), args.append(end.isoformat())
        if account_id:
            where.append("(from_account = ? OR to_account = ?)"), args.extend([account_id, account_id])
        sql = "SELECT * FROM transfers" + (f" WHERE {' AND '.join(where)}" if where else "")
        return [_transfer(r) for r in self.conn.execute(sql + " ORDER BY on_day DESC, id DESC", args)]

    def balances(self) -> dict[int, int]:
        """What each account holds, in its own currency (milli): payments in, plus transfers in, minus out."""
        out = dict(self.received_totals())
        for r in self.conn.execute("SELECT from_account, to_account, sent_milli, received_milli FROM transfers"):
            out[r["from_account"]] = out.get(r["from_account"], 0) - r["sent_milli"]
            out[r["to_account"]] = out.get(r["to_account"], 0) + r["received_milli"]
        return out

    def received_totals(self) -> dict[int, int]:
        """Everything received into each account, in the account's currency (milli)."""
        return {r["account_id"]: r["total"] for r in self.conn.execute(
            "SELECT account_id, SUM(account_milli) AS total FROM payments "
            "WHERE status = 'received' AND account_id IS NOT NULL GROUP BY account_id")}


@dataclass
class Transfer:
    id: int
    on_day: date
    from_account: int
    to_account: int
    sent_milli: int      # in the from-account's currency
    received_milli: int  # in the to-account's currency
    note: str


def _transfer(r) -> Transfer:
    return Transfer(r["id"], date.fromisoformat(r["on_day"]), r["from_account"], r["to_account"], r["sent_milli"],
                    r["received_milli"], r["note"])


def transfer_cost(t: Transfer, accounts: dict[int, Account], rates: Rates) -> tuple[float, int]:
    """The rate you actually got (to-currency per from-currency) and what the move cost in USD milli,
    compared with the market rate that day (never below zero)."""
    src, dst = accounts[t.from_account].currency, accounts[t.to_account].currency
    effective = t.received_milli / t.sent_milli
    lost = rates.convert(t.sent_milli, src, "USD", t.on_day) - rates.convert(t.received_milli, dst, "USD", t.on_day)
    return effective, max(0, lost)
