import logging
import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

from prospector.http import USER_AGENT
from prospector.models import RawLead
from prospector.sources.robots import robots_allowed

log = logging.getLogger(__name__)

# Keejob publishes an RSS feed of its latest offers (advertised in its llms.txt); preferred over HTML scraping.
FEED = "https://www.keejob.com/rss/jobs/"
_COMPANY = re.compile(r"Entre\w*\s*:\s*([^<]+)", re.I)  # the feed spells it "Entreptrise"
_ID = re.compile(r"/offres-emploi/(\d+)/")


class Keejob:
    id = "keejob"
    interval_hours = 6

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        if not robots_allowed(FEED, http, USER_AGENT):
            log.warning("keejob robots.txt disallows %s; skipping", FEED)
            return []
        resp = http.get(FEED)
        resp.raise_for_status()
        out = []
        for item in ET.fromstring(resp.content).iter("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = item.findtext("description") or ""
            company = _COMPANY.search(desc)
            city = title.rsplit(" – ", 1)[1].strip() if " – " in title else None
            pub = item.findtext("pubDate")
            m = _ID.search(link)
            out.append(RawLead(
                source_id=self.id,
                external_id=m.group(1) if m else link,
                url=link,
                title=title,
                body=desc,
                company=company.group(1).strip() if company else None,
                location_text=f"{city}, Tunisia" if city else "Tunisia",
                posted_at=parsedate_to_datetime(pub) if pub else None,
                raw_payload=ET.tostring(item, encoding="unicode"),
            ))
        return out
