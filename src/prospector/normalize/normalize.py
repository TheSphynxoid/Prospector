import hashlib
import re

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from prospector.models import Lead, RawLead
from prospector.normalize.kind import detect_kind
from prospector.normalize.lang import detect_languages
from prospector.normalize.pay import parse_pay
from prospector.normalize.remote import parse_remote
from prospector.normalize.url import canonical_url

_BLOCK_END = re.compile(r"(?i)<(/p|/div|/h\d|/tr|/ul|/ol)\b[^>]*>")
_LINE_END = re.compile(r"(?i)<(br|/li)\b[^>]*>")
_LI = re.compile(r"(?i)<li\b[^>]*>")


def clean_text(text: str, keep_lines: bool = False) -> str:
    """Strip HTML and collapse whitespace. keep_lines keeps paragraph breaks and turns <li> into "- " lines."""
    if "<" in text or "&" in text:
        text = _BLOCK_END.sub("\n\n", text)
        if keep_lines:  # each <li> starts its own "- " line; the closing tag adds nothing
            text = _LI.sub("\n- ", re.sub(r"(?i)</li\s*>", "", text))
        text = _LINE_END.sub("\n", text)
        text = HTMLParser(text).text(separator="")
    if not keep_lines:
        return re.sub(r"\s+", " ", text).strip()
    lines = [re.sub(r"[^\S\n]+", " ", ln).strip() for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def normalize(raw: RawLead) -> Lead:
    title = clean_text(raw.title)
    body = clean_text(raw.body, keep_lines=True)  # the detail page renders paragraphs and lists
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
