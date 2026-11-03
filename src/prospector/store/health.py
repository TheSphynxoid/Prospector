import sqlite3
from dataclasses import dataclass

from prospector.store.db import now_iso


@dataclass
class SourceHealth:
    source_id: str
    last_run: str | None = None
    last_ok: str | None = None
    consecutive_failures: int = 0
    last_count: int | None = None
    last_error: str | None = None
    paused: bool = False
    drift: bool = False


class HealthRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def _ensure(self, source_id: str) -> None:
        self.conn.execute("INSERT OR IGNORE INTO source_health(source_id) VALUES (?)", (source_id,))

    def get(self, source_id: str) -> SourceHealth:
        row = self.conn.execute("SELECT * FROM source_health WHERE source_id = ?", (source_id,)).fetchone()
        if not row:
            return SourceHealth(source_id)
        d = dict(row)
        d["paused"], d["drift"] = bool(d["paused"]), bool(d["drift"])
        return SourceHealth(**d)

    def all(self) -> list[SourceHealth]:
        ids = [r[0] for r in self.conn.execute("SELECT source_id FROM source_health ORDER BY source_id")]
        return [self.get(i) for i in ids]

    def record_success(self, source_id: str, count: int, drift: bool) -> None:
        self._ensure(source_id)
        now = now_iso()
        self.conn.execute(
            "UPDATE source_health SET last_run = ?, last_ok = ?, consecutive_failures = 0, last_count = ?, "
            "last_error = NULL, paused = 0, drift = ? WHERE source_id = ?",
            (now, now, count, int(drift), source_id),
        )

    def record_failure(self, source_id: str, error: str) -> SourceHealth:
        self._ensure(source_id)
        self.conn.execute(
            "UPDATE source_health SET last_run = ?, consecutive_failures = consecutive_failures + 1, "
            "last_error = ? WHERE source_id = ?",
            (now_iso(), error[:500], source_id),
        )
        return self.get(source_id)

    def set_paused(self, source_id: str, paused: bool) -> None:
        self._ensure(source_id)
        self.conn.execute("UPDATE source_health SET paused = ? WHERE source_id = ?",
                          (int(paused), source_id))
