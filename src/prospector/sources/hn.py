import json
import re
from datetime import UTC, datetime

import httpx

from prospector.models import RawLead
from prospector.normalize.normalize import clean_text

SEARCH = "https://hn.algolia.com/api/v1/search_by_date"
ITEM = "https://hn.algolia.com/api/v1/items/{id}"


class HackerNewsHiring:
    """Top-level comments of the latest 'Ask HN: Who is hiring?' thread."""
    id = "hn"
    interval_hours = 6

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        resp = http.get(SEARCH, params={"tags": "story,author_whoishiring", "query": "hiring"})
        resp.raise_for_status()
        story = next((h for h in resp.json().get("hits", []) if "who is hiring" in h["title"].lower()), None)
        if story is None:
            return []
        resp = http.get(ITEM.format(id=story["objectID"]))
        resp.raise_for_status()
        out = []
        for c in resp.json().get("children", []):
            html = c.get("text")
            if not html:
                continue  # deleted / dead comment
            first = clean_text(re.split(r"(?i)<p>", html, maxsplit=1)[0])
            company = first.split("|", 1)[0].strip() if "|" in first else None
            out.append(RawLead(
                source_id=self.id,
                external_id=str(c["id"]),
                url=f"https://news.ycombinator.com/item?id={c['id']}",
                title=first[:120],
                body=html,
                company=company,
                location_text=first,
                posted_at=datetime.fromtimestamp(int(c["created_at_i"]), UTC) if c.get("created_at_i") else None,
                raw_payload=json.dumps({k: v for k, v in c.items() if k != "children"}),
            ))
        return out
