"""Why a lead looks closed, and the reasons the owner said to ignore."""
import json
import sqlite3

from prospector.store.db import now_iso


class ExpiryRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def ignored(self, lead_id: int) -> set[str]:
        r = self.conn.execute("SELECT ignored FROM lead_flags WHERE lead_id = ?", (lead_id,)).fetchone()
        return set(json.loads(r["ignored"])) if r else set()

    def flag(self, lead_id: int, key: str, reason: str) -> None:
        self.conn.execute(
            "INSERT INTO lead_flags(lead_id, closed_key, closed_reason, closed_at) VALUES (?,?,?,?) "
            "ON CONFLICT(lead_id) DO UPDATE SET closed_key = excluded.closed_key, "
            "closed_reason = excluded.closed_reason, closed_at = excluded.closed_at",
            (lead_id, key, reason, now_iso()))

    def flagged_key(self, lead_id: int) -> str | None:
        r = self.conn.execute("SELECT closed_key FROM lead_flags WHERE lead_id = ?", (lead_id,)).fetchone()
        return r["closed_key"] if r else None

    def keep_open(self, lead_id: int) -> None:
        """The owner says it's still open: clear the flag and never raise the same reason again."""
        key = self.flagged_key(lead_id)
        if key is None:
            return
        ignored = sorted(self.ignored(lead_id) | {key})
        self.conn.execute("UPDATE lead_flags SET closed_key = NULL, closed_reason = NULL, closed_at = NULL, "
                          "ignored = ? WHERE lead_id = ?", (json.dumps(ignored), lead_id))

    def flagged_since(self, ts: str) -> list[int]:
        """Starred/applied leads flagged since `ts` (for the digest)."""
        rows = self.conn.execute(
            "SELECT f.lead_id FROM lead_flags f JOIN leads l ON l.id = f.lead_id "
            "WHERE f.closed_at >= ? AND l.status IN ('starred', 'applied') ORDER BY f.closed_at", (ts,))
        return [r["lead_id"] for r in rows.fetchall()]

    def add_ref(self, lead_id: int, source_id: str, external_id: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO lead_refs(lead_id, source_id, external_id) VALUES (?,?,?)",
                          (lead_id, source_id, external_id))

    def refs(self, source_id: str, lead_ids: list[int]) -> dict[int, str]:
        """External ids for these leads; falls back to the raw payload's "id" for leads ingested before refs."""
        if not lead_ids:
            return {}
        marks = ",".join("?" * len(lead_ids))
        out = {r["lead_id"]: r["external_id"] for r in self.conn.execute(
            f"SELECT lead_id, external_id FROM lead_refs WHERE source_id = ? AND lead_id IN ({marks})",
            (source_id, *lead_ids))}
        missing = [i for i in lead_ids if i not in out]
        if missing:
            marks = ",".join("?" * len(missing))
            for r in self.conn.execute(
                    f"SELECT lead_id, json_extract(payload, '$.id') AS ext FROM raw_payloads "
                    f"WHERE source_id = ? AND lead_id IN ({marks})", (source_id, *missing)):
                if r["ext"] is not None:
                    out[r["lead_id"]] = str(r["ext"])
        return out
