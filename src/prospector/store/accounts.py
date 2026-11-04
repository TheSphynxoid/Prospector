"""Where money sits: Freelancer balance, Payoneer, a bank. Archived, never deleted, so history stays."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from prospector.fx import CURRENCIES
from prospector.store.db import now_iso


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

    def received_totals(self) -> dict[int, int]:
        """Everything received into each account, in the account's currency (milli)."""
        return {r["account_id"]: r["total"] for r in self.conn.execute(
            "SELECT account_id, SUM(account_milli) AS total FROM payments "
            "WHERE status = 'received' AND account_id IS NOT NULL GROUP BY account_id")}
