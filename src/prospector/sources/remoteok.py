import json
from datetime import UTC, datetime

import httpx

from prospector.models import RawLead

URL = "https://remoteok.com/api"


class RemoteOK:
    """RemoteOK public API. Their terms require linking back, so the original job URL is kept."""
    id = "remoteok"
    interval_hours = 4

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        resp = http.get(URL)
        resp.raise_for_status()
        out = []
        for job in resp.json():
            if "id" not in job or "position" not in job:  # element 0 is the legal notice
                continue
            lo, hi = job.get("salary_min"), job.get("salary_max")
            out.append(RawLead(
                source_id=self.id,
                external_id=str(job["id"]),
                url=job.get("url") or job.get("apply_url"),
                title=job["position"],
                body=job.get("description") or "",
                company=job.get("company"),
                location_text=f"Remote ({job['location']})" if job.get("location") else "Remote",
                pay_text=f"{lo}-{hi} USD per year" if lo and hi else None,
                posted_at=datetime.fromtimestamp(int(job["epoch"]), UTC) if job.get("epoch") else None,
                raw_payload=json.dumps(job),
            ))
        return out
