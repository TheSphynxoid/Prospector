import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from prospector import fx
from tests.web.conftest import TAILNET

T = fx.today()
HX = {"HX-Request": "true"}


@pytest.fixture
def client(app):
    return TestClient(app, client=TAILNET)


def rates(ctx, **codes):
    ctx.fx.tnd_override = None
    for code, v in codes.items():
        ctx.conn.execute("INSERT OR REPLACE INTO fx_rates VALUES (?,?,?,?)", (T.isoformat(), code, v, "t"))


def job(ctx, **kw):
    return ctx.works.create(**(dict(title="Scraper bot", client="Direct", price_milli=500_000, currency="USD",
                                    started_on=T) | kw))


def toast(r):
    return json.loads(r.headers["HX-Trigger"])["toast"]


def test_jobs_list_grouped_with_paid(client, ctx):
    acc = ctx.accounts.create("Payoneer", "USD")
    wid = job(ctx)
    ctx.works.add_received(wid, 200_000, "USD", T, acc, ctx.fx)
    ctx.works.update(job(ctx, title="Old logo"), stage="closed", ended_on=T)
    page = client.get("/work/jobs").text
    assert "Scraper bot" in page and "$200 of $500" in page and "Old logo" in page
    assert page.index("In progress") < page.index("Closed")
    closed = client.get("/work/jobs?stage=closed").text
    assert "Old logo" in closed and "Scraper bot" not in closed
    assert client.get("/work/jobs?stage=bogus").status_code == 200


def test_job_detail_shows_paid_of_price(client, ctx):
    acc = ctx.accounts.create("Payoneer", "USD")
    wid = job(ctx)
    ctx.works.add_received(wid, 200_000, "USD", T, acc, ctx.fx)
    page = client.get(f"/work/jobs/{wid}").text
    assert "$200 of $500" in page and "Payoneer" in page
    assert client.get("/work/jobs/999").status_code == 404


def test_job_links_back_to_application_and_lead(client, ctx, make_lead):
    lid = ctx.leads.insert(make_lead(title="Go API"))
    aid = ctx.apps.create(lead_id=lid, title="Go API", applied_on=T)
    wid = job(ctx, application_id=aid, lead_id=lid)
    page = client.get(f"/work/jobs/{wid}").text
    assert f'href="/work/applications/{aid}"' in page and f'href="/lead/{lid}"' in page


def test_add_received_payment_inline(client, ctx):
    rates(ctx, EUR=0.9)
    acc = ctx.accounts.create("Wise", "EUR")
    wid = job(ctx)
    r = client.post(f"/work/jobs/{wid}/payments", headers=HX, data={
        "kind": "received", "amount": "1 200,50", "currency": "EUR", "received_on": "", "account_id": str(acc)})
    assert r.status_code == 200 and "€1,200.50" in r.text and "$1,333.89" in r.text
    p = ctx.works.payments(wid)[0]
    assert (p.status, p.received_on, p.usd_rate, p.account_id) == ("received", T, 0.9, acc)
    assert toast(r)["msg"] == "Payment added"


def test_add_expected_payment(client, ctx):
    wid = job(ctx)
    due = (T + timedelta(days=10)).isoformat()
    r = client.post(f"/work/jobs/{wid}/payments", headers=HX,
                    data={"kind": "expected", "amount": "300", "currency": "USD", "due_on": due})
    assert r.status_code == 200 and "Expected" in r.text and ctx.works.payments(wid)[0].due_on.isoformat() == due


@pytest.mark.parametrize("amount", ["abc", "", "-5", "0"])
def test_bad_amount_inline_error(client, ctx, amount):
    wid = job(ctx)
    r = client.post(f"/work/jobs/{wid}/payments", headers=HX,
                    data={"kind": "expected", "amount": amount, "currency": "USD"})
    assert r.status_code == 400 and "amount" in r.text.lower() and ctx.works.payments(wid) == []


def test_received_needs_an_account(client, ctx):
    wid = job(ctx)
    r = client.post(f"/work/jobs/{wid}/payments", headers=HX,
                    data={"kind": "received", "amount": "10", "currency": "USD", "account_id": ""})
    assert r.status_code == 400 and "account" in r.text.lower() and ctx.works.payments(wid) == []


def test_account_without_accounts_prompts_create(client, ctx):
    wid = job(ctx)
    assert 'href="/work/add?what=account"' in client.get(f"/work/jobs/{wid}").text


def test_receive_defaults_last_account(client, ctx):
    a, b = ctx.accounts.create("A", "USD"), ctx.accounts.create("B", "USD")
    wid = job(ctx)
    ctx.works.add_received(wid, 1000, "USD", T - timedelta(days=1), b, ctx.fx)
    pid = ctx.works.add_expected(wid, 5000, "USD", None)
    page = client.get(f"/work/jobs/{wid}").text
    assert f'<option value="{b}" selected>' in page
    r = client.post(f"/work/payments/{pid}/receive", headers=HX, data={"received_on": "", "account_id": ""})
    p = ctx.works.payment(pid)
    assert r.status_code == 200 and (p.status, p.account_id, p.received_on) == ("received", b, T)
    assert a


def test_delete_payment(client, ctx):
    wid = job(ctx)
    pid = ctx.works.add_expected(wid, 5000, "USD", None)
    r = client.post(f"/work/payments/{pid}/delete", headers=HX)
    assert r.status_code == 200 and ctx.works.payments(wid) == [] and toast(r)["msg"] == "Payment removed"
    assert client.post("/work/payments/999/delete").status_code == 404


def test_stage_change_toast_and_undo(client, ctx):
    wid = job(ctx)
    r = client.post(f"/work/jobs/{wid}/stage", headers=HX, data={"stage": "delivered"})
    t = toast(r)
    assert ctx.works.get(wid).stage == "delivered" and t["msg"] == "Marked delivered"
    r = client.post(f"/work/jobs/{wid}/stage", headers=HX, data={"stage": "closed"})
    assert ctx.works.get(wid).ended_on == T
    client.post(toast(r)["undo"], headers=HX)
    w = ctx.works.get(wid)
    assert (w.stage, w.ended_on) == ("delivered", None)
    assert client.post(f"/work/jobs/{wid}/stage", data={"stage": "bogus"}).status_code == 400


def test_archive_account(client, ctx):
    acc = ctx.accounts.create("Old bank", "TND")
    r = client.post(f"/work/accounts/{acc}/archive", headers=HX, follow_redirects=False)
    assert r.status_code in (200, 303) and ctx.accounts.get(acc).archived
