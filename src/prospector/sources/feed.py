"""Small helpers shared by the RSS adapters."""
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime


def rss_items(content: bytes) -> list[tuple[dict[str, str], str]]:
    """(child tag -> stripped text, the item's XML) for each <item> of an RSS 2.0 feed."""
    out = []
    for item in ET.fromstring(content).iter("item"):
        fields = {child.tag: (child.text or "").strip() for child in item}
        out.append((fields, ET.tostring(item, encoding="unicode")))
    return out


def rfc822(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
