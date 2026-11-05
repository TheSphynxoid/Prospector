"""Look up this company: two web searches, fenced as untrusted research, then one assistant answer."""
import re

from prospector.assist.chat import ask, failure, history
from prospector.assist.context import _defang
from prospector.assist.usage import CapReached
from prospector.context import AppContext
from prospector.llm.client import LLMError
from prospector.search.client import Hit, search, search_ready
from prospector.store.assist import Message

OPEN_R, CLOSE_R = "<<<RESEARCH", "RESEARCH>>>"
KEEP = 8
_NUMBERED = re.compile(r"^\d+\. ", re.M)


def _one_line(text: str) -> str:
    return " ".join(_defang(text or "").split())


def research_block(hits: list[Hit]) -> str:
    lines = [OPEN_R]
    for i, h in enumerate(hits, 1):
        lines.append(f"{i}. {_one_line(h.title) or 'Untitled'} — {_one_line(h.url)}")
        if h.snippet.strip():
            lines.append(f"   {_one_line(h.snippet)}")
    lines.append(CLOSE_R)
    return "\n".join(lines)


def split_research(content: str) -> tuple[str, str | None, int]:
    """(text before the research block, the block's body or None, how many results it holds)."""
    start = content.find(OPEN_R)
    end = content.find(CLOSE_R, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return content, None, 0
    body = content[start + len(OPEN_R):end].strip("\n")
    return content[:start].strip(), body, len(_NUMBERED.findall(body))


NAME_LIMIT = 100


def _name(company: str) -> str:
    """The lead's company name is stranger text: one line, markers disarmed, no quotes, capped."""
    return _one_line(company).replace('"', "").strip()[:NAME_LIMIT].strip()


def _hits(ctx: AppContext, name: str) -> list[Hit]:
    seen, out = set(), []
    for query in (f'"{name}"', f'"{name}" reviews OR scam OR layoffs'):
        for h in search(ctx, query, engines=None, max_results=10).results:
            if h.url not in seen:
                seen.add(h.url)
                out.append(h)
    return out[:KEEP]


def lookup(ctx: AppContext, lead_id: int) -> list[Message]:
    lead = ctx.leads.get(lead_id)
    if lead is None or not lead.company or not search_ready(ctx):
        return []
    company = _name(lead.company)
    if not company:
        return []
    intro = f"Look up {company}: what they do, size and location, and any red flags."
    found = _hits(ctx, company)
    if not found:
        return [ctx.assist.add(lead_id, "user", intro),
                ctx.assist.add(lead_id, "assistant", f"Web search found nothing for {company}.")]
    text = f"{intro}\n\n{research_block(found)}"
    past = history(ctx, lead_id)
    user = ctx.assist.add(lead_id, "user", text)
    try:
        reply = ask(ctx, lead_id, [*past, {"role": "user", "content": text}])
    except (CapReached, LLMError) as e:
        return [user, failure(ctx, lead_id, e)]
    return [user, ctx.assist.add(lead_id, "assistant", reply)]
