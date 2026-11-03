import json
import re
from datetime import datetime

import httpx

from prospector.models import Kind, RawLead

URL = "https://api.github.com/search/issues"
_AMOUNT = re.compile(r"\$\s?(\d[\d,]*)")


class GitHubBounties:
    """Open GitHub issues carrying Algora's '💎 Bounty' label."""
    id = "github_bounties"
    interval_hours = 4

    def __init__(self, token: str):
        self.token = token

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        resp = http.get(URL, params={"q": 'label:"💎 Bounty" state:open', "sort": "created", "per_page": 50},
                        headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        out = []
        for issue in resp.json().get("items", []):
            labels = " ".join(l["name"] for l in issue.get("labels", []))
            m = _AMOUNT.search(labels) or _AMOUNT.search(issue["title"])
            repo = issue["repository_url"].rsplit("/repos/", 1)[-1]
            out.append(RawLead(
                source_id=self.id,
                external_id=str(issue["id"]),
                url=issue["html_url"],
                title=issue["title"],
                body=issue.get("body") or issue["title"],
                company=repo,
                location_text="Remote",
                pay_text=f"${m.group(1).replace(',', '')} USD fixed" if m else None,
                posted_at=datetime.fromisoformat(issue["created_at"].replace("Z", "+00:00")),
                kind_hint=Kind.BOUNTY,
                raw_payload=json.dumps(issue),
            ))
        return out
