import httpx

from prospector.models import RawLead
from prospector.sources.feed import rfc822, rss_items

FEEDS = (
    "https://weworkremotely.com/categories/remote-back-end-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-full-stack-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
)


class WeWorkRemotely:
    id = "weworkremotely"
    interval_hours = 4

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        seen: dict[str, RawLead] = {}
        for url in FEEDS:
            resp = http.get(url)
            resp.raise_for_status()
            for f, xml in rss_items(resp.content):
                guid = f.get("guid") or f.get("link", "")
                if not guid or guid in seen:
                    continue
                company, _, role = f.get("title", "").partition(": ")  # titles read "Company: Role"
                if not role:
                    company, role = "", company
                region = f.get("region")
                seen[guid] = RawLead(
                    source_id=self.id, external_id=guid, url=f.get("link") or guid, title=role,
                    body=f.get("description", ""), company=company or None,
                    location_text=f"Remote ({region})" if region else "Remote",
                    posted_at=rfc822(f.get("pubDate")), raw_payload=xml)
        return list(seen.values())
