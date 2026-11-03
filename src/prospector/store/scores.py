import json
import sqlite3

import numpy as np

from prospector.store.db import now_iso

_UPSERT = ("INSERT INTO scores(lead_id, {col}, scored_at) VALUES (?, ?, ?) "
           "ON CONFLICT(lead_id) DO UPDATE SET {col} = excluded.{col}, scored_at = excluded.scored_at")


class ScoreRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def save_stage1(self, lead_id: int, score: float, breakdown: dict) -> None:
        self.conn.execute(
            "INSERT INTO scores(lead_id, stage1, breakdown, scored_at) VALUES (?,?,?,?) "
            "ON CONFLICT(lead_id) DO UPDATE SET stage1 = excluded.stage1, breakdown = excluded.breakdown, "
            "scored_at = excluded.scored_at",
            (lead_id, score, json.dumps(breakdown), now_iso()),
        )

    def save_stage2(self, lead_id: int, result: dict) -> None:
        self.conn.execute(_UPSERT.format(col="stage2"), (lead_id, json.dumps(result), now_iso()))

    def save_embedding(self, lead_id: int, vec: np.ndarray) -> None:
        self.conn.execute(_UPSERT.format(col="embedding"),
                          (lead_id, np.asarray(vec, dtype=np.float32).tobytes(), now_iso()))

    def embeddings(self, ids: list[int]) -> np.ndarray:
        """Embeddings for `ids` (rows for ids without one are skipped)."""
        if not ids:
            return np.zeros((0, 0), dtype=np.float32)
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT lead_id, embedding FROM scores WHERE lead_id IN ({marks}) AND embedding IS NOT NULL", ids
        ).fetchall()
        by_id = {r["lead_id"]: np.frombuffer(r["embedding"], dtype=np.float32) for r in rows}
        vecs = [by_id[i] for i in ids if i in by_id]
        return np.vstack(vecs) if vecs else np.zeros((0, 0), dtype=np.float32)

    def breakdown(self, lead_id: int) -> dict | None:
        row = self.conn.execute("SELECT breakdown FROM scores WHERE lead_id = ?", (lead_id,)).fetchone()
        return json.loads(row["breakdown"]) if row and row["breakdown"] else None

    def top_unreviewed(self, threshold: float, limit: int) -> list[int]:
        rows = self.conn.execute(
            "SELECT s.lead_id FROM scores s JOIN leads l ON l.id = s.lead_id "
            "WHERE s.stage2 IS NULL AND s.stage1 >= ? AND l.status = 'new' "
            "ORDER BY s.stage1 DESC LIMIT ?",
            (threshold, limit),
        ).fetchall()
        return [r["lead_id"] for r in rows]
