"""Text the assistant wrote for the client, marked <<<DRAFT … DRAFT>>>, shown apart from its advice."""
import re
from typing import Literal

OPEN, CLOSE = "<<<DRAFT", "DRAFT>>>"
# Markers on their own lines, or inline ("<<<DRAFT Hi … DRAFT>>>").
_BLOCK = re.compile(r"<<<DRAFT[ \t]*\n?(.*?)\n?[ \t]*DRAFT>>>", re.S)
_MARKERS = re.compile(r"<<<\s*DRAFT|DRAFT\s*>>>", re.I)


def strip_markers(text: str) -> str:
    return _MARKERS.sub("[draft]", text)


def wrap(text: str) -> str:
    return f"{OPEN}\n{strip_markers(text).strip()}\n{CLOSE}"


def _clean(text: str) -> str:
    """Advice text with any unmatched marker removed, so it never shows or gets copied."""
    return re.sub(r"[ \t]{2,}", " ", _MARKERS.sub("", text)).strip()


def split(text: str) -> list[tuple[Literal["text", "draft"], str]]:
    """Advice and drafts in order; a lone marker is dropped and its text stays advice."""
    out: list[tuple[Literal["text", "draft"], str]] = []
    pos = 0
    for m in _BLOCK.finditer(text):
        before = _clean(text[pos:m.start()])
        if before:
            out.append(("text", before))
        out.append(("draft", m.group(1).strip()))
        pos = m.end()
    rest = _clean(text[pos:])
    if rest or not out:
        out.append(("text", rest))
    return out
