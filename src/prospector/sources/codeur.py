import logging
import re

import httpx

from prospector.http import USER_AGENT
from prospector.models import Kind, RawLead
from prospector.sources.feed import rfc822, rss_items
from prospector.sources.robots import robots_allowed

log = logging.getLogger(__name__)
URL = "https://www.codeur.com/projects/c/developpement.rss"  # no query string: robots.txt disallows /*?*
_BUDGET = re.compile(r"Budget\s*:\s*([^<-]+?)\s*-", re.I)


def _euros(s: str) -> list[int]:
    return [int(n.replace(" ", "").replace(" ", "").replace("\xa0", "")) for n in re.findall(r"\d[\d  \xa0]*", s)]


def budget_to_pay(description: str) -> str | None:
    """Codeur's budget bands ("Moins de 500 €", "500 € à 1 000 €", "10 000 € et plus") as pay text."""
    m = _BUDGET.search(description)
    if not m:
        return None
    band, nums = m.group(1), _euros(m.group(1))
    if not nums:
        return None  # "Demande de devis": the client wants quotes
    if re.search(r"moins", band, re.I):
        return f"0-{nums[0]} EUR fixed"
    if len(nums) >= 2:
        return f"{nums[0]}-{nums[1]} EUR fixed"
    return f"{nums[0]} EUR fixed"


class Codeur:
    """French freelance projects (development category), from Codeur's public RSS feed."""
    id = "codeur"
    interval_hours = 6

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        if not robots_allowed(URL, http, USER_AGENT):
            log.warning("codeur robots.txt disallows %s; skipping", URL)
            return []
        resp = http.get(URL)
        resp.raise_for_status()
        out = []
        for f, xml in rss_items(resp.content):
            link = f.get("link")
            if not link:
                continue
            desc = f.get("description", "")
            out.append(RawLead(source_id=self.id, external_id=f.get("guid") or link, url=link,
                               title=f.get("title", ""), body=desc, location_text="Remote",
                               pay_text=budget_to_pay(desc), posted_at=rfc822(f.get("pubDate")),
                               kind_hint=Kind.GIG, raw_payload=xml))
        return out
