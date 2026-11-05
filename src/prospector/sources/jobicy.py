import json
from datetime import UTC, datetime

import httpx

from prospector.models import RawLead

URL = "https://jobicy.com/api/v2/remote-jobs"
TAGS = ("golang", "c++", "rust")
_PERIOD = {"yearly": "year", "monthly": "month", "weekly": "week", "daily": "day", "hourly": "hour"}


def _ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _pay(job: dict) -> str | None:
    lo, hi, cur = job.get("salaryMin"), job.get("salaryMax"), job.get("salaryCurrency")
    if not lo or not cur:
        return None
    return f"{int(lo)}-{int(hi or lo)} {cur} per {_PERIOD.get(job.get('salaryPeriod') or '', 'year')}"


class Jobicy:
    """Jobicy asks for credit and links to its own job page; it allows polling at most once an hour."""
    id = "jobicy"
    interval_hours = 6

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        seen: dict[str, RawLead] = {}
        for tag in TAGS:
            resp = http.get(URL, params={"count": 50, "tag": tag})
            resp.raise_for_status()
            for job in resp.json().get("jobs") or []:
                jid = str(job.get("id") or "")
                if not jid or jid in seen or not job.get("url"):
                    continue
                geo = (job.get("jobGeo") or "").strip()
                seen[jid] = RawLead(
                    source_id=self.id, external_id=jid, url=job["url"], title=job.get("jobTitle") or "",
                    body=job.get("jobDescription") or job.get("jobExcerpt") or "", company=job.get("companyName"),
                    location_text=f"Remote ({geo})" if geo else "Remote", pay_text=_pay(job),
                    posted_at=_ts(job.get("pubDate")), raw_payload=json.dumps(job))
        return list(seen.values())
