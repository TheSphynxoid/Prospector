import sqlite3
from typing import Literal

from prospector.store.db import now_iso

Action = Literal["star", "dismiss", "applied", "reset"]

# Why a lead was dismissed, in menu order. Level and region reasons are detection misses, not topic dislikes.
REASONS: dict[str, str] = {
    "too_senior": "Too senior",
    "no_region": "Can't apply from here",
    "wrong_stack": "Wrong stack",
    "not_interested": "Not interested",
    "other": "Other",
}
REACH_REASONS = ("too_senior", "no_region")

_LATEST = ("SELECT f.id, f.lead_id, f.action, r.reason FROM feedback f "
           "LEFT JOIN dismiss_reasons r ON r.feedback_id = f.id WHERE f.id = "
           "(SELECT MAX(id) FROM feedback g WHERE g.lead_id = f.lead_id) ORDER BY f.lead_id")


class FeedbackRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(self, lead_id: int, action: Action, reason: str | None = None) -> int:
        fid = self.conn.execute("INSERT INTO feedback(lead_id, action, at) VALUES (?,?,?) RETURNING id",
                                (lead_id, action, now_iso())).fetchone()[0]
        if action == "dismiss":
            self.conn.execute("INSERT INTO dismiss_reasons(feedback_id, reason) VALUES (?,?)",
                              (fid, reason if reason in REASONS else "not_interested"))
        return fid

    def delete(self, feedback_id: int, lead_id: int) -> None:
        """Drop one feedback row (undo), only if it belongs to `lead_id`."""
        if self.conn.execute("DELETE FROM feedback WHERE id = ? AND lead_id = ?", (feedback_id, lead_id)).rowcount:
            self.conn.execute("DELETE FROM dismiss_reasons WHERE feedback_id = ?", (feedback_id,))

    def _latest(self) -> list[sqlite3.Row]:
        return self.conn.execute(_LATEST).fetchall()

    def positive_ids(self) -> list[int]:
        return [r["lead_id"] for r in self._latest() if r["action"] in ("star", "applied")]

    def negative_ids(self) -> list[int]:
        """Dismissed leads, minus those dismissed for level or region: their topic may be fine."""
        return [r["lead_id"] for r in self._latest() if r["action"] == "dismiss" and r["reason"] not in REACH_REASONS]

    def misses(self, limit: int = 20) -> list[tuple[int, str]]:
        """(lead_id, reason) of the latest level or region dismissals, newest first."""
        rows = [r for r in self._latest() if r["action"] == "dismiss" and r["reason"] in REACH_REASONS]
        rows.sort(key=lambda r: r["id"], reverse=True)
        return [(r["lead_id"], r["reason"]) for r in rows[:limit]]

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
