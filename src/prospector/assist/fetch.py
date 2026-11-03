"""Fetch a lead's full posting, refusing anything that isn't a public web page."""
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

import httpx

from prospector.context import AppContext
from prospector.http import USER_AGENT, describe_error
from prospector.models import Lead
from prospector.normalize.normalize import clean_text

log = logging.getLogger(__name__)

MAX_HOPS = 3
MAX_BYTES = 2 * 1024 * 1024
MIN_CHARS = 300
JUNK = ("sign in", "log in", "captcha", "enable javascript", "access denied")
_SCRIPTS = re.compile(r"(?is)<(script|style|noscript|svg)\b.*?</\1\s*>")

NOT_PUBLIC = "That address isn't public, so Prospector won't fetch it."
NOT_WEB = "That address isn't a web page."
JUNK_NOTE = "The page needs a login or blocked the request — paste the posting instead."


@dataclass
class FetchResult:
    text: str | None
    origin: str | None  # source | fetched
    note: str | None    # why there is no text


class _Refused(Exception):
    pass


def _check_public(url: httpx.URL, resolve) -> None:
    if url.scheme not in ("http", "https") or not url.host:
        raise _Refused(NOT_WEB)
    try:
        infos = resolve(url.host, url.port or (443 if url.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError):
        raise _Refused("Couldn't find that site (DNS lookup failed).") from None
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if not ip.is_global:  # loopback, private, link-local, CGNAT/tailnet, reserved, multicast...
            raise _Refused(NOT_PUBLIC)


def _robots_ok(client: httpx.Client, url: httpx.URL) -> bool:
    """Like sources.robots, but a site we can't reach raises (reported as such) instead of reading as "disallowed"."""
    resp = client.get(url.copy_with(path="/robots.txt", query=None, fragment=None))
    if resp.status_code >= 400 and resp.status_code < 500:
        return True
    if resp.status_code >= 500:
        return False
    parser = RobotFileParser()
    parser.parse(resp.text.splitlines())
    return parser.can_fetch(USER_AGENT, str(url))


def _read(client: httpx.Client, url: httpx.URL) -> tuple[httpx.Response, str | None]:
    with client.stream("GET", url) as resp:
        if resp.is_redirect or resp.status_code >= 400:
            return resp, None
        ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype not in ("text/html", "text/plain", ""):
            raise _Refused("The page isn't HTML.")
        body = bytearray()
        for chunk in resp.iter_bytes():
            body += chunk
            if len(body) > MAX_BYTES:
                raise _Refused("The page is too large.")
        return resp, body.decode(resp.encoding or "utf-8", errors="replace")


def fetch_posting(lead: Lead, transport: httpx.BaseTransport | None = None, resolve=socket.getaddrinfo) -> FetchResult:
    if "freelancer" in lead.sources:  # the API already returned the full description
        return FetchResult(lead.body, "source", None)
    try:
        url = httpx.URL(lead.canonical_url)
    except httpx.InvalidURL:
        return FetchResult(None, None, NOT_WEB)
    with httpx.Client(transport=transport, follow_redirects=False, timeout=10, trust_env=False,
                      headers={"User-Agent": USER_AGENT}) as client:
        try:
            for _ in range(MAX_HOPS + 1):
                _check_public(url, resolve)
                if not _robots_ok(client, url):
                    raise _Refused("The site's robots.txt disallows fetching this page.")
                resp, body = _read(client, url)
                if resp.is_redirect:
                    url = httpx.URL(urljoin(str(url), resp.headers.get("location", "")))
                    continue
                if resp.status_code in (404, 410):
                    raise _Refused(f"The page wasn't found (HTTP {resp.status_code}) — it may have been taken down.")
                if resp.status_code >= 400:
                    raise _Refused(f"The site blocked the request (HTTP {resp.status_code}).")
                break
            else:
                raise _Refused("Too many redirects.")
        except _Refused as e:
            return FetchResult(None, None, str(e))
        except (httpx.HTTPError, httpx.InvalidURL) as e:
            return FetchResult(None, None, f"Couldn't reach the site ({describe_error(e)}).")
    text = clean_text(_SCRIPTS.sub(" ", body), keep_lines=True)
    head = text[:1000].lower()
    if len(text) < MIN_CHARS or any(w in head for w in JUNK):
        return FetchResult(None, None, JUNK_NOTE)
    return FetchResult(text, "fetched", None)


def refresh_posting(ctx: AppContext, lead_id: int, keep_pasted: bool = False) -> None:
    """keep_pasted: the automatic first-view fetch must not replace what the owner pasted meanwhile."""
    lead = ctx.leads.get(lead_id)
    if lead is None:
        return
    try:
        r = fetch_posting(lead)
    except Exception:  # never let a background fetch crash the job; the owner can paste
        log.exception("posting fetch failed for lead %s", lead_id)
        r = FetchResult(None, None, "Couldn't fetch the page.")
    ctx.assist.set_fetch_result(lead_id, r.text, r.origin, r.note, keep_pasted=keep_pasted)
