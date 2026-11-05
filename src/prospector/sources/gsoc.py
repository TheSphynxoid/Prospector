"""Google Summer of Code: one lead per organisation working in C, C++ or Go, while contributor applications are open.

These are the site's own JSON endpoints, not a documented API: any surprise in their shape gives no leads and a
warning, never an error that pauses the source.
"""
import json
import logging
from datetime import UTC, datetime

import httpx

from prospector.models import Kind, RawLead

log = logging.getLogger(__name__)
BASE = "https://summerofcode.withgoogle.com"
TAGS = {"c", "c++", "go", "golang"}
DEADLINE = "proposal_deadline"  # the milestone that closes contributor applications


def _now() -> datetime:
    return datetime.now(UTC)


def _deadline(program: dict) -> datetime | None:
    for m in program.get("milestones") or []:
        if m.get("name") == DEADLINE and m.get("datetime"):
            return datetime.fromisoformat(m["datetime"].replace("Z", "+00:00"))
    return None


class GSoC:
    id = "gsoc"
    interval_hours = 24

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        resp = http.get(f"{BASE}/api/program/")
        resp.raise_for_status()
        try:
            now = _now()
            open_ = [(d, p) for p in resp.json() if (d := _deadline(p)) and d > now]
            if not open_:
                return []  # between rounds: nothing to apply to
            deadline, program = max(open_, key=lambda x: x[0])
            year = program["slug"]
            orgs = http.get(f"{BASE}/api/program/{year}/organizations/")
            orgs.raise_for_status()
            out = []
            for org in orgs.json():
                tags = [t.lower() for t in org.get("tech_tags") or []]
                if not TAGS & set(tags):
                    continue
                out.append(RawLead(
                    source_id=self.id, external_id=f"{year}:{org['slug']}",
                    url=f"{BASE}/programs/{year}/organizations/{org['slug']}",
                    title=f"GSoC {year}: {org['name']}", company=org["name"],
                    body=f"{org.get('tagline') or ''}\n\n{org.get('description') or ''}\n\nTech: {', '.join(tags)}",
                    location_text="Remote", deadline=deadline.date(), kind_hint=Kind.INTERNSHIP,
                    raw_payload=json.dumps(org)))
            return out
        except (KeyError, TypeError, ValueError, AttributeError) as e:
            log.warning("gsoc: unexpected data shape (%s); no leads", e)
            return []
