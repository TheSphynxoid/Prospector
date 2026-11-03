from datetime import UTC, datetime

from prospector.store.db import connect
from prospector.store.mail import MailRepo


def test_mail_pending_and_needs_you():
    m = MailRepo(connect(":memory:"))
    a = m.insert(b"raw-a", datetime.now(UTC))
    b = m.insert(b"raw-b", datetime.now(UTC))
    assert [i for i, _ in m.pending()] == [a, b]
    m.mark(a, "confirmation", note="LinkedIn: confirm", url="https://x/confirm")
    m.mark(b, "parsed")
    assert m.pending() == []
    items = m.needs_you()
    assert [(i.id, i.url) for i in items] == [(a, "https://x/confirm")]
    m.dismiss_needs_you(a)
    assert m.needs_you() == []
