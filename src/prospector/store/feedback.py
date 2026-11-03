import sqlite3
from typing import Literal

from prospector.store.db import now_iso

Action = Literal["star", "dismiss", "applied", "reset"]

_LATEST = ("SELECT f.lead_id, f.action FROM feedback f WHERE f.id = "
           "(SELECT MAX(id) FROM feedback g WHERE g.lead_id = f.lead_id) ORDER BY f.lead_id")


class FeedbackRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(self, lead_id: int, action: Action) -> int:
        return self.conn.execute("INSERT INTO feedback(lead_id, action, at) VALUES (?,?,?) RETURNING id",
                                 (lead_id, action, now_iso())).fetchone()[0]

    def delete(self, feedback_id: int, lead_id: int) -> None:
        """Drop one feedback row (undo), only if it belongs to `lead_id`."""
        self.conn.execute("DELETE FROM feedback WHERE id = ? AND lead_id = ?", (feedback_id, lead_id))

    def _latest(self, actions: tuple[str, ...]) -> list[int]:
        return [r["lead_id"] for r in self.conn.execute(_LATEST).fetchall() if r["action"] in actions]

    def positive_ids(self) -> list[int]:
        return self._latest(("star", "applied"))

    def negative_ids(self) -> list[int]:
        return self._latest(("dismiss",))

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
