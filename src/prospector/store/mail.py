import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


@dataclass
class NeedsYouItem:
    id: int
    kind: Literal["confirmation", "unparsed"]
    note: str | None
    url: str | None
    received_at: str


class MailRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def insert(self, raw: bytes, received_at: datetime) -> int:
        return self.conn.execute("INSERT INTO mails(raw, received_at) VALUES (?, ?)",
                                 (raw, received_at.isoformat())).lastrowid

    def pending(self) -> list[tuple[int, bytes]]:
        rows = self.conn.execute("SELECT id, raw FROM mails WHERE state = 'pending' ORDER BY id").fetchall()
        return [(r["id"], bytes(r["raw"])) for r in rows]

    def get_raw(self, id: int) -> bytes | None:
        row = self.conn.execute("SELECT raw FROM mails WHERE id = ?", (id,)).fetchone()
        return bytes(row["raw"]) if row else None

    def mark(self, id: int, state: Literal["parsed", "unparsed", "confirmation"],
             note: str | None = None, url: str | None = None) -> None:
        self.conn.execute("UPDATE mails SET state = ?, note = ?, url = ? WHERE id = ?",
                          (state, note, url, id))

    def needs_you(self) -> list[NeedsYouItem]:
        rows = self.conn.execute(
            "SELECT id, state, note, url, received_at FROM mails "
            "WHERE state IN ('confirmation', 'unparsed') AND dismissed = 0 ORDER BY id DESC"
        ).fetchall()
        return [NeedsYouItem(r["id"], r["state"], r["note"], r["url"], r["received_at"]) for r in rows]

    def dismiss_needs_you(self, id: int) -> None:
        self.conn.execute("UPDATE mails SET dismissed = 1 WHERE id = ?", (id,))
