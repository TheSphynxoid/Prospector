import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path

_SCHEMA = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")


class Database:
    """One sqlite3 connection per thread to the same database.

    A single connection shared between the web threads and the scheduler interleaves statements
    (cursors come back empty, lastrowid belongs to another insert), so each thread gets its own.
    Exposes the subset of the sqlite3.Connection API the repositories use.
    """

    def __init__(self, path: Path | str):
        if str(path) == ":memory:":
            # Named shared-cache memory DB so every thread's connection sees the same data.
            self._target, self._uri = f"file:prospector-{uuid.uuid4().hex}?mode=memory&cache=shared", True
        else:
            self._target, self._uri = str(path), False
        self._local = threading.local()
        self._keepalive = self._open()  # memory DBs live as long as one connection is open
        self._keepalive.executescript(_SCHEMA)

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._target, uri=self._uri, check_same_thread=False,
                               isolation_level=None, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = self._local.conn = self._open()
        return c

    def execute(self, sql: str, params=()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def executescript(self, sql: str) -> sqlite3.Cursor:
        return self.conn.executescript(sql)

    def backup(self, target: "Database | sqlite3.Connection") -> None:
        self.conn.backup(target.conn if isinstance(target, Database) else target)

    def close(self) -> None:
        c = getattr(self._local, "conn", None)
        if c is not None:
            c.close()
            self._local.conn = None
        self._keepalive.close()


def connect(path: Path | str) -> Database:
    return Database(path)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()
