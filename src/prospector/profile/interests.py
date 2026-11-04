"""Interests: whole-word phrases that move a lead's score up or down, plus a preview and suggestions."""
import re
from collections import Counter
from functools import lru_cache

from prospector.models import Lead, Status
from prospector.profile.model import Interest

# Tokens like C++, C#, .NET and node.js: a match can't touch a word character or one of these on either side.
_BEFORE, _AFTER = r"(?<![\w+#.])", r"(?![\w+#])"
STOP = frozenset("""a an and are as at be but by for from has have in is it of on or our the to we with you your
will this that who all any can into via per job role team work new remote senior junior mid full time part
le la les de des du un une et en au aux pour par sur avec dans est nous vous""".split())


@lru_cache(maxsize=512)
def _pattern(phrase: str) -> re.Pattern:
    return re.compile(_BEFORE + re.escape(phrase) + _AFTER, re.IGNORECASE)


def matches(interest: Interest, title: str, body: str) -> bool:
    text = title if interest.where == "title" else f"{title}\n{body}"
    return bool(_pattern(interest.phrase).search(text))


def keyword_score(lead: Lead, interests: list[Interest]) -> float:
    total = sum(i.weight for i in interests if matches(i, lead.title, lead.body or ""))
    return min(max(total / 3, 0.0), 1.0)


def preview(leads, interest: Interest, limit: int = 3) -> tuple[int, list[str]]:
    """How many current (new or starred) leads it matches, with a few example titles."""
    count, titles = 0, []
    for status in (Status.NEW, Status.STARRED):
        for row in leads.list(status, limit=5000):
            if matches(interest, row.lead.title, row.lead.body or ""):
                count += 1
                if len(titles) < limit:
                    titles.append(row.lead.title)
    return count, titles


def _words(title: str) -> list[str]:
    return [w for w in re.findall(r"[\w+#.]+", title.lower()) if not w.strip(".").isdigit()]


def suggest(titles: list[str], known: set[str], limit: int = 12) -> list[str]:
    """Words (3+ letters) and two-word phrases seen at least twice, minus stop-words and what is already known."""
    known = {k.lower() for k in known}
    counts: Counter[str] = Counter()
    for title in titles:
        words = [w.strip(".") for w in _words(title)]
        seen = set()
        for w in words:
            if len(w) >= 3 and w not in STOP:
                seen.add(w)
        for a, b in zip(words, words[1:]):
            if a not in STOP and b not in STOP and len(a) >= 2 and len(b) >= 2:
                seen.add(f"{a} {b}")
        counts.update(seen)
    out = [w for w, n in counts.most_common() if n >= 2 and w not in known and w not in STOP]
    return out[:limit]
