"""Text the assistant wrote for the client, marked <<<DRAFT … DRAFT>>>, shown apart from its advice."""
import re
from typing import Literal

OPEN, CLOSE = "<<<DRAFT", "DRAFT>>>"
_BLOCK = re.compile(r"<<<DRAFT[ \t]*\n(.*?)\n[ \t]*DRAFT>>>", re.S)
_MARKERS = re.compile(r"<<<\s*DRAFT|DRAFT\s*>>>", re.I)


def strip_markers(text: str) -> str:
    return _MARKERS.sub("[draft]", text)


def wrap(text: str) -> str:
    return f"{OPEN}\n{strip_markers(text).strip()}\n{CLOSE}"


def split(text: str) -> list[tuple[Literal["text", "draft"], str]]:
    """Advice and drafts in order; an unclosed marker stays ordinary text."""
    out: list[tuple[Literal["text", "draft"], str]] = []
    pos = 0
    for m in _BLOCK.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            out.append(("text", before))
        out.append(("draft", m.group(1).strip()))
        pos = m.end()
    rest = text[pos:].strip()
    if rest or not out:
        out.append(("text", rest))
    return out
