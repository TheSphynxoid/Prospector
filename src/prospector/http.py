import httpx

from prospector import __version__

USER_AGENT = f"prospector/{__version__} (+https://prospector.thesphynx.net)"


def make_client() -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True)
