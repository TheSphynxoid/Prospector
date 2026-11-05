"""Outreachy: paid remote internships. One lead per open project on the public project-selection page."""
import logging
import re
from datetime import date, datetime

import httpx
from selectolax.lexbor import LexborHTMLParser

from prospector.models import Kind, RawLead

log = logging.getLogger(__name__)
URL = "https://www.outreachy.org/apply/project-selection/"
_DATE = re.compile(r"([A-Z][a-z]+)\.?\s+(\d{1,2}),\s+(\d{4})")
_PROJECT = re.compile(r"^(?P<community>.+?)\s+project\s+#\d+$")  # "Git project #1"; closed ones read "… closed project #1"


def parse_deadline(text: str) -> date | None:
    m = _DATE.search(text or "")
    if not m:
        return None
    month = m.group(1)[:3]  # "Nov.", "Sept.", "March"
    try:
        return datetime.strptime(f"{month} {m.group(2)} {m.group(3)}", "%b %d %Y").date()
    except ValueError:
        return None


class Outreachy:
    id = "outreachy"
    interval_hours = 24

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        resp = http.get(URL)
        resp.raise_for_status()
        doc = LexborHTMLParser(resp.text)
        page_deadline = None
        for h in doc.css("h3"):
            if "Final Applications Due" in h.text():
                page_deadline = parse_deadline(h.text())
        out = []
        for card in doc.css("div.card[id]"):
            header = card.css_first(".card-header")
            head = " ".join(header.text().split()) if header else ""
            m = None if " closed project #" in head else _PROJECT.match(head)
            title = card.css_first(".card-body p strong")
            if not m or not title:
                continue
            community, name = m["community"], " ".join(title.text().split())
            skills = [" ".join(x.text().split()) for x in card.css(".row .col-sm")][1:]  # first row is the heading
            deadline = None
            for p in card.css("p"):
                if "Deadline" in p.text():
                    deadline = parse_deadline(p.text())
            out.append(RawLead(
                source_id=self.id, external_id=card.attributes["id"], url=f"{URL}#{card.attributes['id']}",
                title=f"Outreachy: {name} ({community})", company=community,
                body=f"{name}\n\nSkills: {', '.join(skills)}", location_text="Remote",
                deadline=deadline or page_deadline, kind_hint=Kind.INTERNSHIP, raw_payload=card.html or ""))
        if not out:
            log.warning("outreachy: no open projects found on the page")
        return out
