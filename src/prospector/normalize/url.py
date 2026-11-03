from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_DROP = {"ref", "refid", "trackingid", "source", "gclid", "fbclid"}


def canonical_url(url: str) -> str:
    """Stable form of a posting URL so the same job on the same site dedupes."""
    parts = urlsplit(url.strip())
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    query = sorted(
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _DROP
    )
    return urlunsplit(("https", host, parts.path.rstrip("/"), urlencode(query), ""))
