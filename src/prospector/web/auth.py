import ipaddress
import time
from urllib.parse import urlsplit

import httpx
import jwt
from fastapi import Request
from fastapi.responses import PlainTextResponse

TAILNET = ipaddress.ip_network("100.64.0.0/10")
EXEMPT = {"/healthz"}
_CERTS_TTL = 3600


class AccessVerifier:
    """Validates Cloudflare Access JWTs against the team's published signing keys."""

    def __init__(self, team_domain: str, aud: str, http: httpx.Client):
        self.issuer = f"https://{team_domain}"
        self.certs_url = f"https://{team_domain}/cdn-cgi/access/certs"
        self.aud = aud
        self._http = http
        self._keys: jwt.PyJWKSet | None = None
        self._fetched = 0.0

    def _keyset(self, force: bool = False) -> jwt.PyJWKSet:
        if force or self._keys is None or time.time() - self._fetched > _CERTS_TTL:
            resp = self._http.get(self.certs_url)
            resp.raise_for_status()
            self._keys = jwt.PyJWKSet.from_dict({"keys": resp.json()["keys"]})
            self._fetched = time.time()
        return self._keys

    def verify(self, token: str) -> dict:
        try:
            kid = jwt.get_unverified_header(token).get("kid")
            keys = self._keyset()
            key = next((k for k in keys.keys if k.key_id == kid), None)
            if key is None:  # keys rotated
                key = next((k for k in self._keyset(force=True).keys if k.key_id == kid), None)
            if key is None:
                raise PermissionError("unknown signing key")
            return jwt.decode(token, key.key, algorithms=["RS256"], audience=self.aud, issuer=self.issuer)
        except (jwt.PyJWTError, httpx.HTTPError, KeyError, ValueError) as e:
            raise PermissionError(str(e)) from e


def _from_tailnet(request: Request) -> bool:
    try:
        return request.client is not None and ipaddress.ip_address(request.client.host) in TAILNET
    except ValueError:
        return False


_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def allowed_hosts(settings) -> set[str]:
    hosts = {"localhost", "127.0.0.1", "::1", *(h.lower() for h in settings.allowed_hosts)}
    if settings.dashboard_url:
        hosts.add(urlsplit(settings.dashboard_url).hostname or "")
    if settings.tailscale_ip:
        hosts.add(settings.tailscale_ip)
    return hosts - {""}


def make_host_middleware(hosts: set[str]):
    """Answer only to known hostnames. Trust is by peer IP (tailnet) and Origin is compared with Host, so a
    DNS-rebound attacker name pointing at the server would otherwise pass both checks."""

    async def middleware(request: Request, call_next):
        host = urlsplit(f"//{request.headers.get('host', '')}").hostname or ""
        if host.lower() not in hosts:
            return PlainTextResponse("unknown host", status_code=400)
        return await call_next(request)

    return middleware


def make_same_origin_middleware(exempt: frozenset[str] = frozenset({"/ingest/mail"})):
    """Refuse state-changing requests a browser marks as coming from another site (CSRF).

    Requests with neither header (curl, very old browsers) pass; the access check still applies to them.
    """

    async def middleware(request: Request, call_next):
        if request.method not in _SAFE_METHODS and request.url.path not in exempt:
            site = request.headers.get("sec-fetch-site")
            origin = request.headers.get("origin")
            if (site is not None and site != "same-origin") or (
                    origin is not None and urlsplit(origin).netloc != request.headers.get("host")):
                return PlainTextResponse("cross-origin request refused", status_code=403)
        return await call_next(request)

    return middleware


def make_access_middleware(verifier: AccessVerifier | None):
    """Tailnet clients pass; everyone else needs a valid Cf-Access-Jwt-Assertion. Fails closed."""

    async def middleware(request: Request, call_next):
        if request.url.path in EXEMPT or _from_tailnet(request):
            return await call_next(request)
        token = request.headers.get("cf-access-jwt-assertion")
        if verifier is None or not token:
            return PlainTextResponse("forbidden", status_code=403)
        try:
            verifier.verify(token)
        except PermissionError:
            return PlainTextResponse("forbidden", status_code=403)
        return await call_next(request)

    return middleware
