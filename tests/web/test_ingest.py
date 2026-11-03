from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from prospector.store.db import connect
from prospector.store.mail import MailRepo
from prospector.web.ingest import make_ingest_router, sign

SECRET = b"topsecret"
NOW = datetime(2026, 11, 3, 9, tzinfo=UTC)


@pytest.fixture
def setup():
    mail = MailRepo(connect(":memory:"))
    app = FastAPI()
    app.include_router(make_ingest_router(mail, SECRET, clock=lambda: NOW))
    return TestClient(app), mail


def post(client, body: bytes, ts: int | None = None, sig: str | None = None):
    ts = int(NOW.timestamp()) if ts is None else ts
    sig = sig or "sha256=" + sign(SECRET, str(ts), body)
    return client.post("/ingest/mail", content=body,
                       headers={"X-Prospector-Timestamp": str(ts), "X-Prospector-Signature": sig})


def test_sign_cross_language_vector():
    # Same vector is asserted in mail-bridge/test/index.spec.ts
    assert sign(b"s", "1700000000", b"hello") == "572a25936663b163a3e39109afc634683bd8a51ddc845600f628e37b49218bf1"


def test_ingest_accepts_valid_signature(setup):
    client, mail = setup
    r = post(client, b"raw mime")
    assert r.status_code == 202 and r.json()["id"] == 1
    assert mail.pending() == [(1, b"raw mime")]


def test_ingest_rejects_bad_signature(setup):
    client, mail = setup
    assert post(client, b"raw", sig="sha256=" + "0" * 64).status_code == 401
    assert mail.pending() == []


def test_ingest_rejects_missing_headers(setup):
    client, _ = setup
    assert client.post("/ingest/mail", content=b"x").status_code == 401


def test_ingest_rejects_stale_timestamp(setup):
    client, _ = setup
    assert post(client, b"raw", ts=int(NOW.timestamp()) + 301).status_code == 401
    assert post(client, b"raw", ts=int(NOW.timestamp()) - 300).status_code == 202


def test_ingest_rejects_oversize(setup):
    client, _ = setup
    assert post(client, b"x" * (5 * 1024 * 1024 + 1)).status_code == 413
