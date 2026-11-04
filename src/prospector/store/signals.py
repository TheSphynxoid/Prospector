import sqlite3

from prospector.store.db import now_iso


class LeadSignalsRepo:
    """Signals that change after a lead is first seen; today only Freelancer's bid count."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def set_bids(self, lead_id: int, n: int) -> None:
        self.conn.execute(
            "INSERT INTO lead_signals(lead_id, bid_count, updated_at) VALUES (?,?,?) "
            "ON CONFLICT(lead_id) DO UPDATE SET bid_count = excluded.bid_count, updated_at = excluded.updated_at",
            (lead_id, n, now_iso()))

    def bids(self, lead_id: int) -> int | None:
        row = self.conn.execute("SELECT bid_count FROM lead_signals WHERE lead_id = ?", (lead_id,)).fetchone()
        return row[0] if row else None
