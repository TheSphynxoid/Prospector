from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx


def robots_allowed(url: str, http: httpx.Client, user_agent: str) -> bool:
    """robots.txt check. Missing robots.txt (4xx) allows; server/network errors deny."""
    parts = urlsplit(url)
    try:
        resp = http.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
    except httpx.HTTPError:
        return False
    if resp.status_code >= 500:
        return False
    if resp.status_code >= 400:
        return True
    parser = RobotFileParser()
    parser.parse(resp.text.splitlines())
    return parser.can_fetch(user_agent, url)
