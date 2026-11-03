import re

import httpx

from prospector import __version__

USER_AGENT = f"prospector/{__version__} (+https://prospector.thesphynx.net)"


def describe_error(e: BaseException) -> str:
    """Error text safe to store, log or email: no URLs (query strings / paths can carry keys and tokens)."""
    if isinstance(e, httpx.HTTPStatusError):
        return f"HTTP {e.response.status_code} from {e.request.url.host}"
    if isinstance(e, httpx.RequestError):
        try:
            return f"{type(e).__name__} contacting {e.request.url.host}"
        except RuntimeError:  # request not attached
            return type(e).__name__
    return f"{type(e).__name__}: " + re.sub(r"https?://\S+", "<url>", str(e))[:300]


def make_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
