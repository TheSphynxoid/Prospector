import email
import email.policy
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from email.message import EmailMessage
from email.utils import parseaddr

from selectolax.lexbor import LexborHTMLParser

from prospector.models import RawLead
from prospector.sources.alerts import generic

# Sender domain (e.g. "linkedin.com") -> parser; filled per site once real samples exist.
PARSERS: dict[str, Callable[[EmailMessage], list[RawLead]]] = {}

_CONFIRM = re.compile(r"confirm|verify|v[ée]rifi|activate|activer|valider", re.I)
_URL = re.compile(r"https?://[^\s<>\"')]+")


@dataclass
class AlertResult:
    leads: list[RawLead] = field(default_factory=list)
    confirmation_url: str | None = None
    parsed: bool = False


def _part_text(msg: EmailMessage, subtype: str) -> str | None:
    part = msg.get_body(preferencelist=(subtype,))
    if part is None:
        return None
    try:
        return part.get_content()
    except (LookupError, UnicodeDecodeError):
        return part.get_payload(decode=True).decode("latin-1", errors="replace")


def sender_domain(msg: EmailMessage) -> str:
    addr = parseaddr(str(msg.get("from", "")))[1].lower()
    domain = addr.rsplit("@", 1)[-1]
    return ".".join(domain.split(".")[-2:])


def _links(plain: str | None, html: str | None) -> list[str]:
    if html:
        hrefs = [a.attributes.get("href") or "" for a in LexborHTMLParser(html).css("a[href]")]
        return [h for h in hrefs if h.startswith("http")]
    return _URL.findall(plain or "")


def parse_alert(raw: bytes) -> AlertResult:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    plain, html = _part_text(msg, "plain"), _part_text(msg, "html")
    subject = str(msg.get("subject", ""))
    if _CONFIRM.search(subject) or _CONFIRM.search((plain or "")[:2000]):
        links = _links(plain, html)
        link = next((l for l in links if _CONFIRM.search(l)), links[0] if links else None)
        if link:
            return AlertResult(confirmation_url=link, parsed=True)
    parser = PARSERS.get(sender_domain(msg))
    leads = parser(msg) if parser else generic.extract(msg, html)
    return AlertResult(leads=leads, parsed=bool(leads))
