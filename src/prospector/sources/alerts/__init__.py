import email
import email.policy
import logging

import httpx

from prospector.models import RawLead
from prospector.sources.alerts.parse import parse_alert
from prospector.store.mail import MailRepo

log = logging.getLogger(__name__)


def _describe(raw: bytes) -> str:
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        return f"{msg.get('from', '?')} — {msg.get('subject', '?')}"
    except Exception:  # noqa: BLE001
        return "unreadable message"


class AlertsSource:
    """Parses alert emails pushed to /ingest/mail by the mail-bridge Worker."""
    id = "alerts"
    interval_hours = 0.25

    def __init__(self, mail: MailRepo):
        self.mail = mail

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        out: list[RawLead] = []
        for mail_id, raw in self.mail.pending():
            try:
                res = parse_alert(raw)
            except Exception as e:  # noqa: BLE001 — one bad email must not block the rest
                log.warning("alert mail %s failed to parse: %s", mail_id, e)
                self.mail.mark(mail_id, "unparsed", note=f"{_describe(raw)} — error: {e}")
                continue
            if res.confirmation_url:
                self.mail.mark(mail_id, "confirmation", note=_describe(raw), url=res.confirmation_url)
            elif res.parsed:
                self.mail.mark(mail_id, "parsed")
                out.extend(res.leads)
            else:
                self.mail.mark(mail_id, "unparsed", note=_describe(raw))
        return out
