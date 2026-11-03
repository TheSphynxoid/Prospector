from datetime import UTC, datetime
from pathlib import Path

import httpx

from prospector.sources.alerts import AlertsSource
from prospector.sources.alerts import parse as parse_mod
from prospector.sources.alerts.parse import parse_alert
from prospector.store.db import connect
from prospector.store.mail import MailRepo

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "alerts"


def raw(name):
    return (FIX / name).read_bytes()


def test_confirmation_detected():
    res = parse_alert(raw("confirm_fr.eml"))
    assert res.confirmation_url == "https://www.welcometothejungle.com/fr/alerts/confirm?token=abc123"
    assert res.leads == []


def test_unknown_sender_generic_links():
    res = parse_alert(raw("generic_jobs.eml"))
    assert res.parsed and res.confirmation_url is None
    assert [l.title for l in res.leads] == ["Senior Go Backend Engineer at Acme", "Développeur C++ temps réel - Tunis"]
    assert all(l.source_id == "alerts" for l in res.leads)
    assert res.leads[0].url == "https://jobs-board.example/job/101?utm_source=alert"


def test_unknown_sender_no_links_is_unparsed():
    res = parse_alert(raw("unknown_sender.eml"))
    assert not res.parsed and res.leads == []


def test_html_only_latin1_does_not_crash():
    res = parse_alert(raw("html_only_latin1.eml"))
    assert not res.parsed


def fetch_all(mail):
    with httpx.Client() as http:
        return AlertsSource(mail).fetch(http)


def test_source_marks_states_and_needs_you():
    mail = MailRepo(connect(":memory:"))
    now = datetime.now(UTC)
    for name in ("confirm_fr.eml", "generic_jobs.eml", "unknown_sender.eml"):
        mail.insert(raw(name), now)
    leads = fetch_all(mail)
    assert len(leads) == 2
    assert mail.pending() == []
    kinds = {i.kind: i for i in mail.needs_you()}
    assert kinds["confirmation"].url.startswith("https://www.welcometothejungle.com")
    assert "random-newsletter.example" in kinds["unparsed"].note


def test_one_bad_message_does_not_stop_others(monkeypatch):
    mail = MailRepo(connect(":memory:"))
    now = datetime.now(UTC)
    bad = mail.insert(b"boom", now)
    mail.insert(raw("generic_jobs.eml"), now)
    real = parse_mod.parse_alert

    def flaky(data):
        if data == b"boom":
            raise RuntimeError("parser exploded")
        return real(data)

    monkeypatch.setattr("prospector.sources.alerts.parse_alert", flaky)
    assert len(fetch_all(mail)) == 2
    item = next(i for i in mail.needs_you() if i.id == bad)
    assert "parser exploded" in item.note


def test_alerts_source_id_and_interval():
    s = AlertsSource(MailRepo(connect(":memory:")))
    assert s.id == "alerts" and s.interval_hours == 0.25
