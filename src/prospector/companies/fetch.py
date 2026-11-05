"""Read one company's jobs through its board's official public API, keeping only tech roles."""
import html
import json
import re
from datetime import UTC, datetime

import httpx

from prospector.models import RawLead
from prospector.store.companies import Company

SOURCE_ID = "company_boards"
_B, _E = r"(?<![\w-])", r"(?![\w-])"
_TECH = re.compile(
    _B + r"(engineer(ing|s)?|developers?|d[ée]veloppeu(r|se)s?|software|back-?end|front-?end|full[- ]?stack|"
    r"platform|infrastructure|sre|devops|data|ml|embedded|firmware|systems|security|programmers?|golang|go|"
    r"rust|interns?|internships?|graduate|new grad)" + _E + r"|" + _B + r"c\+\+", re.I)
_NON_TECH = re.compile(
    r"\b(sales|account (executive|manager)|marketing|recruit\w*|legal|counsel|finance|accountant|people partner|"
    r"customer support|support specialist)\b", re.I)
_BUILDER = re.compile(r"\b(engineer\w*|developer\w*|software)\b", re.I)
_REMOTE_WORD = re.compile(r"\bremote\b\s*[-–:,]?\s*", re.I)


class BoardError(Exception):
    """The board answered, but not with the shape its API documents."""


def is_tech_role(title: str) -> bool:
    if not _TECH.search(title or ""):
        return False
    return not _NON_TECH.search(title) or bool(_BUILDER.search(title))


def _when(value) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value / 1000, tz=UTC)  # Lever: milliseconds
        dt = datetime.fromisoformat(str(value))
    except (ValueError, OverflowError, OSError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _location(places: list[str], remote: bool) -> str | None:
    """`Remote (<places>)` for a remote job, else the places joined. "Remote (Canada)" reads as Canada."""
    out: list[str] = []
    for p in places:
        p = " ".join(str(p or "").split())
        if _REMOTE_WORD.search(p):
            remote = True
            p = _REMOTE_WORD.sub("", p).strip()
            if p.startswith("(") and p.endswith(")"):
                p = p[1:-1].strip()
        if p and p not in out:
            out.append(p)
    joined = ", ".join(out)
    if remote:
        return f"Remote ({joined})" if joined else "Remote"
    return joined or None


def _get_json(http: httpx.Client, url: str):
    r = http.get(url)
    r.raise_for_status()
    try:
        return r.json()
    except (json.JSONDecodeError, ValueError):
        raise BoardError("the board did not answer with JSON") from None


def _jobs_list(data, key: str | None) -> list:
    if key:
        jobs = data.get(key) if isinstance(data, dict) else None
    else:
        jobs = data
    if not isinstance(jobs, list):
        raise BoardError("unexpected answer from the board")
    return [j for j in jobs if isinstance(j, dict)]


def _lead(company: Company, job_id, title, url, body, location, posted, name) -> RawLead | None:
    title = " ".join(str(title or "").split())
    if not title or not url or not is_tech_role(title):
        return None
    return RawLead(source_id=SOURCE_ID, external_id=f"{company.board}:{company.token}:{job_id}", url=str(url),
                   title=title, body=str(body or ""), company=name or company.display_name,
                   location_text=location, posted_at=posted)


def _greenhouse(http, c: Company):
    data = _get_json(http, f"https://boards-api.greenhouse.io/v1/boards/{c.token}/jobs?content=true")
    jobs = _jobs_list(data, "jobs")
    name = next((j["company_name"] for j in jobs if j.get("company_name")), None)
    leads = []
    for j in jobs:
        loc = (j.get("location") or {}).get("name") if isinstance(j.get("location"), dict) else None
        leads.append(_lead(c, j.get("id"), j.get("title"), j.get("absolute_url"),
                           html.unescape(j.get("content") or ""),  # HTML sent HTML-escaped
                           _location([loc] if loc else [], False),
                           _when(j.get("first_published") or j.get("updated_at")), name))
    return name, leads


def _lever(http, c: Company):
    jobs = _jobs_list(_get_json(http, f"https://api.lever.co/v0/postings/{c.token}?mode=json"), None)
    leads = []
    for j in jobs:
        cat = j.get("categories") if isinstance(j.get("categories"), dict) else {}
        places = cat.get("allLocations") or ([cat["location"]] if cat.get("location") else [])
        body = "\n\n".join(x for x in (j.get("descriptionPlain"), j.get("additionalPlain")) if x)
        leads.append(_lead(c, j.get("id"), j.get("text"), j.get("hostedUrl"), body,
                           _location(list(places), j.get("workplaceType") == "remote"),
                           _when(j.get("createdAt")), None))
    return None, leads


def _ashby(http, c: Company):
    jobs = _jobs_list(_get_json(http, f"https://api.ashbyhq.com/posting-api/job-board/{c.token}"), "jobs")
    leads = []
    for j in jobs:
        if j.get("isListed") is False:
            continue
        places = [j.get("location")] + [s.get("location") for s in j.get("secondaryLocations") or []
                                        if isinstance(s, dict)]
        remote = bool(j.get("isRemote")) or j.get("workplaceType") == "Remote"
        leads.append(_lead(c, j.get("id"), j.get("title"), j.get("jobUrl"),
                           j.get("descriptionPlain") or j.get("descriptionHtml"),
                           _location([p for p in places if p], remote), _when(j.get("publishedAt")), None))
    return None, leads


_FETCHERS = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}


def fetch_board(http: httpx.Client, company: Company) -> tuple[str | None, list[RawLead]]:
    """(the board's company name if it says, the tech jobs). Raises BoardError or httpx.HTTPError."""
    fetcher = _FETCHERS.get(company.board)
    if fetcher is None:
        raise BoardError(f"unknown board {company.board}")
    name, leads = fetcher(http, company)
    return name, [l for l in leads if l is not None]
