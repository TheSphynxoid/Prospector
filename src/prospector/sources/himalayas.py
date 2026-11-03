import json
from datetime import UTC, datetime

import httpx

from prospector.models import Kind, RawLead

URL = "https://himalayas.app/jobs/api?limit=100"
_PERIODS = {"annual": "per year", "monthly": "per month", "hourly": "per hour", "weekly": "per week"}


def _ts(value) -> datetime | None:
    return datetime.fromtimestamp(int(value), UTC) if value else None


class Himalayas:
    id = "himalayas"
    interval_hours = 6

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        resp = http.get(URL)
        resp.raise_for_status()
        out = []
        for job in resp.json().get("jobs", []):
            regions = ", ".join(job.get("locationRestrictions") or []) or "Worldwide"
            pay = None
            if job.get("minSalary") and job.get("currency"):
                pay = f"{job['minSalary']}-{job.get('maxSalary') or job['minSalary']} {job['currency']} " \
                      f"{_PERIODS.get(job.get('salaryPeriod'), '')}".strip()
            expiry = _ts(job.get("expiryDate"))
            out.append(RawLead(
                source_id=self.id,
                external_id=job["guid"],
                url=job.get("applicationLink") or job["guid"],
                title=job["title"],
                body=job.get("description") or job.get("excerpt") or "",
                company=job.get("companyName"),
                location_text=f"Remote ({regions})",
                pay_text=pay,
                posted_at=_ts(job.get("pubDate")),
                deadline=expiry.date() if expiry else None,
                kind_hint=Kind.CONTRACT if job.get("employmentType") == "Contractor" else None,
                raw_payload=json.dumps(job),
            ))
        return out
