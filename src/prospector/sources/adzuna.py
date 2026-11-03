import json
from datetime import datetime

import httpx

from prospector.models import Kind, RawLead

URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"
_CURRENCY = {"fr": "EUR", "de": "EUR", "gb": "GBP", "au": "AUD", "us": "USD", "ca": "CAD", "nl": "EUR"}


class Adzuna:
    id = "adzuna"
    interval_hours = 6

    def __init__(self, app_id: str, app_key: str, countries=("fr", "de", "gb", "au"),
                 what: str = "software developer"):
        self.app_id, self.app_key, self.countries, self.what = app_id, app_key, countries, what

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        out = []
        for country in self.countries:
            resp = http.get(URL.format(country=country), params={
                "app_id": self.app_id, "app_key": self.app_key, "what": self.what,
                "results_per_page": 50, "content-type": "application/json",
            })
            resp.raise_for_status()
            for job in resp.json().get("results", []):
                lo, hi = job.get("salary_min"), job.get("salary_max")
                pay = f"{int(lo)}-{int(hi or lo)} {_CURRENCY.get(country, '')} per year".strip() if lo else None
                out.append(RawLead(
                    source_id=self.id,
                    external_id=f"{country}:{job['id']}",
                    url=job["redirect_url"],
                    title=job["title"],
                    body=job.get("description") or "",
                    company=(job.get("company") or {}).get("display_name"),
                    location_text=f"{(job.get('location') or {}).get('display_name', '')} [{country.upper()}]",
                    pay_text=pay,
                    posted_at=datetime.fromisoformat(job["created"].replace("Z", "+00:00")) if job.get("created") else None,
                    kind_hint=Kind.CONTRACT if job.get("contract_type") == "contract" else None,
                    raw_payload=json.dumps(job),
                ))
        return out
