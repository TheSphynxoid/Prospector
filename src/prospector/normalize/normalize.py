import hashlib
import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from prospector.models import Lead, RawLead
from prospector.normalize.kind import detect_kind
from prospector.normalize.lang import detect_languages
from prospector.normalize.pay import parse_pay
from prospector.normalize.remote import parse_remote
from prospector.normalize.url import canonical_url

_BLOCK_END = re.compile(r"(?i)<(br|/p|/div|/li|/h\d|/tr)\b[^>]*>")


def clean_text(text: str) -> str:
    if "<" in text or "&" in text:
        text = HTMLParser(_BLOCK_END.sub("\n", text)).text(separator="")
    return re.sub(r"\s+", " ", text).strip()


def normalize(raw: RawLead) -> Lead:
    title = clean_text(raw.title)
    body = clean_text(raw.body)
    remote, region = parse_remote(raw.location_text, title, body)
    company = clean_text(raw.company) if raw.company else None
    digest = hashlib.sha256(f"{title}|{company or ''}|{body}".encode()).hexdigest()
    return Lead(
        canonical_url=canonical_url(raw.url),
        title=title,
        company=company,
        kind=detect_kind(raw),
        remote=remote,
        remote_region=region,
        locations=[raw.location_text.strip()] if raw.location_text and raw.location_text.strip() else [],
        pay=parse_pay(raw.pay_text),
        languages=detect_languages(f"{title} {body}"),
        deadline=raw.deadline,
        posted_at=raw.posted_at,
        body=body,
        content_hash=digest,
        sources=[raw.source_id],
    )
