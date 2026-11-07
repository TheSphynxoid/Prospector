"""Arabic freelance projects (development category), from Mostaql's public RSS feed."""
import logging
import re

import httpx

from prospector.http import USER_AGENT
from prospector.models import Kind, RawLead
from prospector.sources.feed import rfc822, rss_items
from prospector.sources.robots import robots_allowed

log = logging.getLogger(__name__)
URL = "https://mostaql.com/rss?category=development"  # robots.txt only disallows /search* and /ajax/
_ID = re.compile(r"/(?:go|project)/(\d+)")


class Mostaql:
    """About 20 new development projects a day; no budget in the feed (it's on the project page)."""
    id = "mostaql"
    interval_hours = 3

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        if not robots_allowed(URL, http, USER_AGENT):
            log.warning("mostaql robots.txt disallows %s; skipping", URL)
            return []
        resp = http.get(URL)
        resp.raise_for_status()
        out = []
        for f, xml in rss_items(resp.content):
            m = _ID.search(f.get("link", ""))
            if not m:
                continue
            out.append(RawLead(source_id=self.id, external_id=m[1],
                               url=f"https://mostaql.com/project/{m[1]}",  # what /go/{id} redirects to, minus the slug
                               title=f.get("title", ""), body=f.get("description", ""), location_text="Remote",
                               posted_at=rfc822(f.get("pubDate")), kind_hint=Kind.GIG, raw_payload=xml))
        return out
