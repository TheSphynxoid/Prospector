"""PFE internships in Tunisia, from PFE Books' public WordPress API (WP Job Manager listings).

robots.txt allows everything but WordPress internals, and the site has no terms against reuse. We read the
JSON the site itself serves instead of its HTML pages.
"""
import json
import logging
from datetime import UTC, datetime

import httpx

from prospector.http import USER_AGENT
from prospector.models import Kind, RawLead
from prospector.sources.robots import robots_allowed

log = logging.getLogger(__name__)
API = "https://pfebooks.com/wp-json/wp/v2/job-listings"
# The site's job-categories ids: Informatique, IA & Données; Systèmes, Réseaux & Cloud; Web, Mobile & Design.
CATEGORIES = "1285,1289,1282"
FIELDS = "id,date_gmt,link,title,content,meta,job-categories,job-types"
PER_PAGE = 100
MAX_PAGES = 8  # about 440 IT listings in November 2026: 5 pages
# job-types ids: the study level each listing asks for, and how it is worked.
LEVELS = {1296: "Ingénierie", 1294: "Master", 1293: "Licence", 1374: "Niveau ouvert"}
REMOTE, HYBRID = 1276, 1279


def _posted(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value).replace(tzinfo=UTC) if value else None
    except ValueError:
        return None


class PfeBooks:
    id = "pfebooks"
    interval_hours = 6

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        if not robots_allowed(API, http, USER_AGENT):
            log.warning("pfebooks robots.txt disallows %s; skipping", API)
            return []
        out, page, pages = [], 1, 1
        while page <= min(pages, MAX_PAGES):
            resp = http.get(API, params={"job-categories": CATEGORIES, "per_page": PER_PAGE, "page": page,
                                         "_fields": FIELDS})
            resp.raise_for_status()
            pages = int(resp.headers.get("X-WP-TotalPages", "1") or 1)
            out += [lead for item in resp.json() if (lead := self._lead(item))]
            page += 1
        return out

    def _lead(self, item: dict) -> RawLead | None:
        meta = item.get("meta") or {}
        if meta.get("_filled"):
            return None
        types = item.get("job-types") or []
        where = (meta.get("_job_location") or "").strip() or "Tunisie"
        if REMOTE in types or meta.get("_remote_position"):
            where += " (Télétravail)"
        elif HYBRID in types:
            where += " (Hybride)"
        extra = []
        if levels := [LEVELS[t] for t in types if t in LEVELS]:
            extra.append(f"Niveau : {', '.join(levels)}")
        if site := (meta.get("_company_website") or "").strip():
            extra.append(f"Site : {site}")
        if apply := (meta.get("_application") or "").strip():
            extra.append(f"Postuler : {apply}")
        body = (item.get("content") or {}).get("rendered", "") + "".join(f"<p>{x}</p>" for x in extra)
        return RawLead(
            source_id=self.id, external_id=str(item["id"]), url=item["link"],
            title=(item.get("title") or {}).get("rendered", ""), body=body,
            company=(meta.get("_company_name") or "").strip() or None, location_text=where,
            posted_at=_posted(item.get("date_gmt")), kind_hint=Kind.PFE,
            raw_payload=json.dumps(item, ensure_ascii=False),
        )
