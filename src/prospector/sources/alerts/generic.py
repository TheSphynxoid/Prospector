import re
from email.message import EmailMessage

from selectolax.lexbor import LexborHTMLParser

from prospector.models import RawLead
from prospector.normalize.normalize import clean_text

_JOBBY_PATH = re.compile(r"job|emploi|offre|career|position|vacanc", re.I)


def extract(msg: EmailMessage, html: str | None) -> list[RawLead]:
    """Fallback for unknown senders: job-looking links with descriptive anchor text."""
    if not html:
        return []
    out, seen = [], set()
    for a in LexborHTMLParser(html).css("a[href]"):
        href = (a.attributes.get("href") or "").strip()
        text = clean_text(a.text() or "")
        path = re.sub(r"^https?://[^/]+", "", href)
        if len(text.split()) < 4 or not _JOBBY_PATH.search(path) or href in seen:
            continue
        seen.add(href)
        out.append(RawLead(source_id="alerts", external_id=href, url=href, title=text, body=text,
                           raw_payload=f"{msg.get('from', '')} | {msg.get('subject', '')}"))
    return out
