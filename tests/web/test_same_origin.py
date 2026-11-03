import time

import pytest
from fastapi.testclient import TestClient

from prospector.models import Status
from prospector.web.ingest import sign
from tests.web.conftest import TAILNET


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


@pytest.fixture
def lid(ctx, make_lead):
    return ctx.leads.insert(make_lead())


def test_cross_site_post_refused(ctx, client, lid):
    r = client.post(f"/lead/{lid}/star", headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    assert ctx.leads.get(lid).status is Status.NEW


def test_foreign_origin_refused(ctx, client, lid):
    assert client.post(f"/lead/{lid}/star", headers={"Origin": "https://evil.example"}).status_code == 403
    assert ctx.leads.get(lid).status is Status.NEW


def test_same_origin_post_allowed(ctx, client, lid):
    r = client.post(f"/lead/{lid}/star", headers={"Origin": "http://testserver", "Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 200 and ctx.leads.get(lid).status is Status.STARRED


def test_no_headers_allowed(client, lid):
    assert client.post(f"/lead/{lid}/star").status_code == 200


def test_get_not_checked(client):
    assert client.get("/", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 200


def test_ingest_exempt(ctx, client):
    ts, body = str(int(time.time())), b"raw mime"
    sig = "sha256=" + sign(ctx.settings.bridge_secret.get_secret_value().encode(), ts, body)
    r = client.post("/ingest/mail", content=body, headers={
        "X-Prospector-Timestamp": ts, "X-Prospector-Signature": sig,
        "Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 202
