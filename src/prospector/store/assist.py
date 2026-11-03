"""The lead assistant's data: one chat per lead, the full posting and the last bid draft."""
import json
import sqlite3
from dataclasses import dataclass

from prospector.store.db import now_iso


@dataclass
class Message:
    id: int
    lead_id: int
    role: str  # user | assistant | error (shown, never sent to the model)
    content: str
    at: str


@dataclass
class AssistRow:
    posting: str | None
    posting_origin: str | None  # source | fetched | pasted
    fetch_note: str | None
    fetch_tried: bool
    bid: dict | None


def _msg(r: sqlite3.Row) -> Message:
    return Message(r["id"], r["lead_id"], r["role"], r["content"], r["at"])


class AssistRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def add(self, lead_id: int, role: str, content: str) -> Message:
        r = self.conn.execute("INSERT INTO lead_messages(lead_id, role, content, at) VALUES (?,?,?,?) RETURNING *",
                              (lead_id, role, content, now_iso())).fetchone()
        return _msg(r)

    def messages(self, lead_id: int) -> list[Message]:
        rows = self.conn.execute("SELECT * FROM lead_messages WHERE lead_id = ? ORDER BY id", (lead_id,))
        return [_msg(r) for r in rows.fetchall()]

    def recent(self, lead_id: int, n: int) -> list[Message]:
        """The last `n` messages the model may see (no errors), oldest first."""
        rows = self.conn.execute("SELECT * FROM lead_messages WHERE lead_id = ? AND role != 'error' "
                                 "ORDER BY id DESC LIMIT ?", (lead_id, n)).fetchall()
        return [_msg(r) for r in reversed(rows)]

    def clear(self, lead_id: int) -> None:
        self.conn.execute("DELETE FROM lead_messages WHERE lead_id = ?", (lead_id,))
        self.conn.execute("UPDATE lead_assist SET bid = NULL WHERE lead_id = ?", (lead_id,))

    def get(self, lead_id: int) -> AssistRow:
        r = self.conn.execute("SELECT * FROM lead_assist WHERE lead_id = ?", (lead_id,)).fetchone()
        if r is None:
            return AssistRow(None, None, None, False, None)
        return AssistRow(r["posting"], r["posting_origin"], r["fetch_note"], bool(r["fetch_tried"]),
                         json.loads(r["bid"]) if r["bid"] else None)

    def _upsert(self, lead_id: int, **cols) -> None:
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        updates = ", ".join(f"{c} = excluded.{c}" for c in cols)
        self.conn.execute(f"INSERT INTO lead_assist(lead_id, {names}) VALUES (?, {marks}) "
                          f"ON CONFLICT(lead_id) DO UPDATE SET {updates}", (lead_id, *cols.values()))

    def set_posting(self, lead_id: int, text: str, origin: str) -> None:
        self._upsert(lead_id, posting=text, posting_origin=origin)

    def set_fetch_result(self, lead_id: int, text: str | None, origin: str | None, note: str | None) -> None:
        if text is None:  # a failed fetch keeps whatever posting is already there
            self._upsert(lead_id, fetch_note=note, fetch_tried=1)
        else:
            self._upsert(lead_id, posting=text, posting_origin=origin, fetch_note=note, fetch_tried=1)

    def set_bid(self, lead_id: int, bid: dict) -> None:
        self._upsert(lead_id, bid=json.dumps(bid))
