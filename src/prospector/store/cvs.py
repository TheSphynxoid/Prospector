"""The owner's CVs: several files, checked by content, stored under DATA_DIR/cv with random names."""
from __future__ import annotations

import io
import re
import sqlite3
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from prospector.store.db import now_iso

MAX_CV_BYTES = 5 * 1024 * 1024
TYPES = {"pdf": "application/pdf",
         "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


@dataclass
class Cv:
    id: int
    label: str
    language: str | None
    filename: str
    stored_name: str
    size: int
    content_type: str
    is_main: bool
    uploaded_at: str


def sniff(data: bytes) -> Literal["pdf", "docx"]:
    """What the file really is, from its bytes. Raises ValueError for anything but PDF or DOCX."""
    if not data:
        raise ValueError("The file is empty.")
    if len(data) > MAX_CV_BYTES:
        raise ValueError("The file is over 5 MB.")
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" in z.namelist():
                    return "docx"
        except zipfile.BadZipFile:
            pass
    raise ValueError("Upload a PDF or DOCX file.")


def safe_filename(name: str, kind: str) -> str:
    """The name shown and used for downloads: no paths, only plain characters, the real extension."""
    base = Path(name.replace("\\", "/")).name
    stem = re.sub(r"[^A-Za-z0-9._ -]", "", base.rsplit(".", 1)[0]).strip(" .") or "cv"
    return f"{stem[:95]}.{kind}"


def _row(r) -> Cv:
    return Cv(r["id"], r["label"], r["language"], r["filename"], r["stored_name"], r["size"], r["content_type"],
              bool(r["is_main"]), r["uploaded_at"])


class CvRepo:
    def __init__(self, conn: sqlite3.Connection, root: Path):
        self.conn = conn
        self.root = Path(root)

    def _write(self, data: bytes) -> tuple[str, str]:
        kind = sniff(data)
        self.root.mkdir(parents=True, exist_ok=True)
        stored = f"{uuid.uuid4().hex}.{kind}"
        (self.root / stored).write_bytes(data)
        return kind, stored

    def add(self, label: str, language: str | None, filename: str, data: bytes) -> int:
        label = (label or "").strip()
        if not label:
            raise ValueError("Give the CV a label, like “English, backend”.")
        kind, stored = self._write(data)
        first = self.conn.execute("SELECT COUNT(*) AS n FROM cvs").fetchone()["n"] == 0
        return self.conn.execute(
            "INSERT INTO cvs(label, language, filename, stored_name, size, content_type, is_main, uploaded_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (label[:80], (language or "").strip()[:20] or None, safe_filename(filename, kind), stored, len(data),
             TYPES[kind], int(first), now_iso())).lastrowid

    def list(self) -> list[Cv]:
        return [_row(r) for r in self.conn.execute("SELECT * FROM cvs ORDER BY is_main DESC, uploaded_at DESC, id DESC")]

    def get(self, id: int) -> Cv | None:
        r = self.conn.execute("SELECT * FROM cvs WHERE id = ?", (id,)).fetchone()
        return _row(r) if r else None

    def path(self, cv: Cv) -> Path:
        return self.root / cv.stored_name

    def set_main(self, id: int) -> None:
        if self.get(id) is None:
            raise LookupError(id)
        self.conn.execute("UPDATE cvs SET is_main = (id = ?)", (id,))

    def replace(self, id: int, filename: str, data: bytes) -> None:
        cv = self.get(id)
        if cv is None:
            raise LookupError(id)
        kind, stored = self._write(data)
        self.conn.execute("UPDATE cvs SET filename = ?, stored_name = ?, size = ?, content_type = ?, uploaded_at = ? "
                          "WHERE id = ?", (safe_filename(filename, kind), stored, len(data), TYPES[kind], now_iso(), id))
        self.path(cv).unlink(missing_ok=True)

    def delete(self, id: int) -> None:
        cv = self.get(id)
        if cv is None:
            return
        self.conn.execute("DELETE FROM cvs WHERE id = ?", (id,))
        self.path(cv).unlink(missing_ok=True)
        if cv.is_main:
            r = self.conn.execute("SELECT id FROM cvs ORDER BY uploaded_at DESC, id DESC LIMIT 1").fetchone()
            if r:
                self.set_main(r["id"])
