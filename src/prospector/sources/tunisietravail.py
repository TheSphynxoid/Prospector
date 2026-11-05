import html
import json
import logging
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from prospector.http import USER_AGENT
from prospector.models import RawLead
from prospector.sources.robots import robots_allowed

log = logging.getLogger(__name__)
URL = "https://www.tunisietravail.net/wp-json/wp/v2/posts"
QUERIES = ("développeur", "developpeur", "informatique", "stage", "pfe")
TZ = ZoneInfo("Africa/Tunis")
# Most posts on this board are not tech jobs; keep the ones whose title says they are.
_TECH = re.compile(r"d[ée]veloppeu[rs]e?|informati|software|logiciel|\bstage\b|\bpfe\b|devops|\bdata\b|\bweb\b|"
                   r"full ?stack|back ?end|front ?end|ing[ée]nieur|programm", re.I)


def is_tech(title: str) -> bool:
    return bool(_TECH.search(title))


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=TZ)  # WordPress "date" is the site's local time


class TunisieTravail:
    id = "tunisietravail"
    interval_hours = 6

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        if not robots_allowed(URL, http, USER_AGENT):
            log.warning("tunisietravail robots.txt disallows %s; skipping", URL)
            return []
        seen: dict[str, RawLead] = {}
        for q in QUERIES:
            resp = http.get(URL, params={"search": q, "per_page": 20, "_fields": "id,date,title,link,excerpt,content"})
            resp.raise_for_status()
            for post in resp.json() or []:
                pid = str(post.get("id") or "")
                title = html.unescape((post.get("title") or {}).get("rendered") or "").strip()
                if not pid or pid in seen or not post.get("link") or not is_tech(title):
                    continue
                body = (post.get("content") or {}).get("rendered") or (post.get("excerpt") or {}).get("rendered") or ""
                seen[pid] = RawLead(source_id=self.id, external_id=pid, url=post["link"], title=title, body=body,
                                    location_text="Tunisia", posted_at=_ts(post.get("date")),
                                    raw_payload=json.dumps(post))
        return list(seen.values())
