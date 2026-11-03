import json
from datetime import UTC, datetime

import httpx

from prospector.models import RawLead

URL = "https://www.arbeitnow.com/api/job-board-api"


class Arbeitnow:
    id = "arbeitnow"
    interval_hours = 6

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        resp = http.get(URL)
        resp.raise_for_status()
        out = []
        for job in resp.json().get("data", []):
            location = job.get("location") or ""
            if job.get("remote") and "remote" not in location.lower():
                location = f"{location}; Remote".strip("; ")
            out.append(RawLead(
                source_id=self.id,
                external_id=job["slug"],
                url=job["url"],
                title=job["title"],
                body=job.get("description") or "",
                company=job.get("company_name"),
                location_text=location or None,
                posted_at=datetime.fromtimestamp(int(job["created_at"]), UTC) if job.get("created_at") else None,
                raw_payload=json.dumps(job),
            ))
        return out
