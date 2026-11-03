import json
from datetime import UTC, datetime

import httpx

from prospector.models import Kind, RawLead

URL = "https://www.freelancer.com/api/projects/0.1/projects/active/"
DEFAULT_QUERIES = ("golang", "c++", "spring boot", "next.js", "devops")


class Freelancer:
    id = "freelancer"
    interval_hours = 3

    def __init__(self, queries=DEFAULT_QUERIES):
        self.queries = queries

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        seen: dict[int, RawLead] = {}
        for q in self.queries:
            resp = http.get(URL, params={"query": q, "limit": 50, "full_description": "true"})
            resp.raise_for_status()
            for p in resp.json().get("result", {}).get("projects", []):
                if p["id"] in seen:
                    continue
                budget, code = p.get("budget") or {}, (p.get("currency") or {}).get("code", "")
                lo, hi = budget.get("minimum"), budget.get("maximum")
                period = "per hour" if p.get("type") == "hourly" else "fixed"
                seen[p["id"]] = RawLead(
                    source_id=self.id,
                    external_id=str(p["id"]),
                    url=f"https://www.freelancer.com/projects/{p['seo_url']}",
                    title=p["title"],
                    body=p.get("description") or p.get("preview_description") or "",
                    location_text="Remote",
                    pay_text=f"{int(lo)}-{int(hi or lo)} {code} {period}" if lo else None,
                    posted_at=datetime.fromtimestamp(int(p["time_submitted"]), UTC) if p.get("time_submitted") else None,
                    kind_hint=Kind.GIG,
                    raw_payload=json.dumps(p),
                )
        return list(seen.values())
