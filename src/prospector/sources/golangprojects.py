import httpx

from prospector.models import RawLead
from prospector.sources.feed import rfc822, rss_items

URL = "https://www.golangprojects.com/rss.xml"


class Golangprojects:
    """A Go-only board. Its feed has no dates; remote or on-site is read from the text."""
    id = "golangprojects"
    interval_hours = 6

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        resp = http.get(URL)
        resp.raise_for_status()
        out = []
        for f, xml in rss_items(resp.content):
            link = f.get("link") or f.get("guid")
            if not link:
                continue
            title = " ".join(f.get("title", "").split())  # the feed pads " @ " with non-breaking spaces
            role, _, company = title.rpartition(" @ ")  # titles read "Role @ Company"
            out.append(RawLead(
                source_id=self.id, external_id=f.get("guid") or link, url=link, title=role or company,
                body=f.get("description", ""), company=company if role else None,
                posted_at=rfc822(f.get("pubDate")), raw_payload=xml))
        return out
