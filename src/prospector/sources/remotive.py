import json
from datetime import UTC, datetime

import httpx

from prospector.models import Kind, RawLead

URL = "https://remotive.com/api/remote-jobs?category=software-dev"


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class Remotive:
    id = "remotive"
    interval_hours = 4

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        resp = http.get(URL)
        resp.raise_for_status()
        return [
            RawLead(
                source_id=self.id,
                external_id=str(job["id"]),
                url=job["url"],
                title=job["title"],
                body=job.get("description") or "",
                company=job.get("company_name"),
                location_text=f"Remote ({job['candidate_required_location']})"
                if job.get("candidate_required_location") else "Remote",
                pay_text=job.get("salary") or None,
                posted_at=_ts(job.get("publication_date")),
                kind_hint=Kind.CONTRACT if job.get("job_type") in ("contract", "freelance") else None,
                raw_payload=json.dumps(job),
            )
            for job in resp.json().get("jobs", [])
        ]
