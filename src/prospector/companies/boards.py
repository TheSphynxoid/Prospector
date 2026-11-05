"""Turn a Greenhouse, Lever or Ashby link into (board, token)."""
import re
from urllib.parse import parse_qs, urlsplit

BOARDS = ("greenhouse", "lever", "ashby")
LABEL = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby"}
_HOSTS = {
    "boards.greenhouse.io": "greenhouse", "job-boards.greenhouse.io": "greenhouse",
    "boards-api.greenhouse.io": "greenhouse", "jobs.lever.co": "lever", "jobs.ashbyhq.com": "ashby",
}
_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
_NOT_TOKENS = {"embed", "v1"}


def _token(value: str | None) -> str | None:
    t = (value or "").strip().lower()
    return t if _TOKEN.match(t) and t not in _NOT_TOKENS else None


def parse_board_url(url: str) -> tuple[str, str] | None:
    try:
        parts = urlsplit((url or "").strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https"):
        return None
    host = (parts.hostname or "").lower()
    host = host.removeprefix("www.")
    board = _HOSTS.get(host)
    if board is None:
        return None
    segs = [s for s in parts.path.split("/") if s]
    if host == "boards-api.greenhouse.io":
        # /v1/boards/<t>/...
        token = segs[2] if len(segs) >= 3 and segs[0] == "v1" and segs[1] == "boards" else None
    elif segs[:2] == ["embed", "job_board"] and board == "greenhouse":
        token = (parse_qs(parts.query).get("for") or [None])[0]
    else:
        token = segs[0] if segs else None
    token = _token(token)
    return (board, token) if token else None
