import pytest
from fastapi.testclient import TestClient

from tests.store.test_cvs import PDF
from tests.web.conftest import TAILNET


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


def upload(client, name="cv.pdf", data=PDF, label="English", language="en"):
    return client.post("/settings/profile/cvs", data={"label": label, "language": language},
                       files={"file": (name, data, "application/pdf")}, headers={"HX-Request": "true"})


def test_cv_upload_route_errors_inline(client, ctx):
    r = upload(client, data=b"MZ not a pdf")
    assert r.status_code == 400 and "PDF or DOCX" in r.text and ctx.cvs.list() == []
    r = upload(client, label="  ")
    assert r.status_code == 400 and "label" in r.text.lower()


def test_cv_download_safe_name(client, ctx):
    r = upload(client, name="../../evil cv<>.pdf")
    assert r.status_code == 200 and "evil cv" in r.text
    cv = ctx.cvs.list()[0]
    assert "/" not in cv.stored_name and ".." not in cv.stored_name
    d = client.get(f"/settings/profile/cvs/{cv.id}/download")
    assert d.status_code == 200 and d.content == PDF
    assert d.headers["content-disposition"] == 'attachment; filename="evil cv.pdf"'
    assert d.headers["x-content-type-options"] == "nosniff"
    assert client.get("/settings/profile/cvs/999/download").status_code == 404


def test_cv_main_and_delete_routes(client, ctx):
    upload(client, label="A"), upload(client, label="B")
    a, b = sorted(c.id for c in ctx.cvs.list())
    r = client.post(f"/settings/profile/cvs/{b}/main", headers={"HX-Request": "true"})
    assert r.status_code == 200 and ctx.cvs.get(b).is_main
    r = client.post(f"/settings/profile/cvs/{b}/delete", headers={"HX-Request": "true"})
    assert ctx.cvs.get(b) is None and ctx.cvs.get(a).is_main
