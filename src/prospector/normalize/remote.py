import re

from prospector.models import Remote

_HYBRID = re.compile(r"\bhybrid[e]?\b", re.I)
_REMOTE = re.compile(r"\bremote\b|t[ée]l[ée]travail|work from home|\bwfh\b|à distance|100% distanciel", re.I)
_REGION = re.compile(r"remote\s*[(\-–:]\s*([^)]+?)\s*\)?\s*$", re.I)


def parse_remote(location_text: str | None, title: str, body: str) -> tuple[Remote, str | None]:
    head = f"{location_text or ''} {title}"
    if _HYBRID.search(head):
        return Remote.HYBRID, None
    if _REMOTE.search(head) or _REMOTE.search(body or ""):
        m = _REGION.search(location_text or "")
        return Remote.YES, (m.group(1) if m else None)
    if location_text and location_text.strip():
        return Remote.NO, None
    return Remote.UNKNOWN, None
