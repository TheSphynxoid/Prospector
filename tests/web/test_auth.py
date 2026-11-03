from fastapi.testclient import TestClient

from tests.web.conftest import OUTSIDE, TAILNET


def test_tailnet_allowed_without_jwt(app):
    assert TestClient(app, client=TAILNET).get("/").status_code == 200


def test_non_tailnet_without_jwt_forbidden(app):
    assert TestClient(app, client=OUTSIDE).get("/").status_code == 403


def test_localhost_without_jwt_forbidden(app):
    assert TestClient(app, client=("127.0.0.1", 5000)).get("/").status_code == 403


def test_valid_jwt_allowed(app, make_token):
    r = TestClient(app, client=OUTSIDE).get("/", headers={"Cf-Access-Jwt-Assertion": make_token()})
    assert r.status_code == 200


def test_wrong_aud_forbidden(app, make_token):
    r = TestClient(app, client=OUTSIDE).get("/", headers={"Cf-Access-Jwt-Assertion": make_token(aud="other")})
    assert r.status_code == 403


def test_expired_jwt_forbidden(app, make_token):
    r = TestClient(app, client=OUTSIDE).get("/", headers={"Cf-Access-Jwt-Assertion": make_token(exp_in=-60)})
    assert r.status_code == 403


def test_garbage_jwt_forbidden(app):
    r = TestClient(app, client=OUTSIDE).get("/", headers={"Cf-Access-Jwt-Assertion": "not.a.jwt"})
    assert r.status_code == 403


def test_healthz_exempt(app):
    r = TestClient(app, client=OUTSIDE).get("/healthz")
    assert r.status_code == 200 and r.text == "ok"


def test_ingest_requires_access_too(app):
    assert TestClient(app, client=OUTSIDE).post("/ingest/mail", content=b"x").status_code == 403
