import httpx
import pytest

from prospector.assist.fetch import fetch_posting, refresh_posting

PAGE = "<html><body><script>var x=1;</script><h1>Go API</h1><p>" + "Build a REST API in Go. " * 30 + "</p></body></html>"


def resolver(ip="93.184.216.34"):
    def resolve(host, port, *a, **k):
        return [(2, 1, 6, "", (ip, port))]
    return resolve


class Site:
    """MockTransport handler: robots.txt 404 unless set; records every non-robots request."""

    def __init__(self, routes, robots=None):
        self.routes, self.robots, self.seen = routes, robots, []

    def __call__(self, request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=self.robots) if self.robots else httpx.Response(404)
        self.seen.append(str(request.url))
        return self.routes[str(request.url)]()


def html(body=PAGE, ctype="text/html; charset=utf-8", status=200):
    return lambda: httpx.Response(status, text=body, headers={"content-type": ctype})


def redirect(to):
    return lambda: httpx.Response(302, headers={"location": to})


def run(lead, site, ip="93.184.216.34"):
    return fetch_posting(lead, transport=httpx.MockTransport(site), resolve=resolver(ip))


@pytest.fixture
def lead(make_lead):
    return make_lead(canonical_url="https://jobs.example/1", body="short body", sources=["remotive"])


def test_freelancer_uses_body(make_lead):
    site = Site({})
    r = run(make_lead(body="full description", sources=["freelancer"]), site)
    assert (r.text, r.origin, r.note) == ("full description", "source", None) and site.seen == []


def test_fetches_and_cleans(lead):
    r = run(lead, Site({"https://jobs.example/1": html()}))
    assert r.origin == "fetched" and r.note is None
    assert "Build a REST API in Go." in r.text and "var x" not in r.text and "<p>" not in r.text


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "100.101.83.89", "169.254.1.1", "192.168.1.2", "::1",
                                "fd00::1", "::ffff:127.0.0.1"])
def test_blocks_private_addresses(lead, ip):
    site = Site({"https://jobs.example/1": html()})
    r = run(lead, site, ip)
    assert r.text is None and r.note == "That address isn't public, so Prospector won't fetch it."
    assert site.seen == []


def test_redirect_to_private_blocked(lead):
    site = Site({"https://jobs.example/1": redirect("http://127.0.0.1:8000/settings")})
    r = fetch_posting(lead, transport=httpx.MockTransport(site),
                      resolve=lambda host, port, *a, **k: [(2, 1, 6, "", ("127.0.0.1" if host == "127.0.0.1"
                                                                           else "93.184.216.34", port))])
    assert r.text is None and "isn't public" in r.note
    assert site.seen == ["https://jobs.example/1"]


def test_follows_public_redirect(lead):
    site = Site({"https://jobs.example/1": redirect("/job/1"), "https://jobs.example/job/1": html()})
    assert run(lead, site).origin == "fetched"


def test_too_many_redirects(lead):
    routes = {f"https://jobs.example/{i}": redirect(f"https://jobs.example/{i + 1}") for i in range(1, 6)}
    r = run(lead, Site(routes))
    assert r.text is None and r.note == "Too many redirects."


def test_rejects_non_http_scheme(make_lead):
    r = run(make_lead(canonical_url="file:///etc/passwd", sources=["hn"]), Site({}))
    assert r.text is None and r.note == "That address isn't a web page."


def test_rejects_non_html(lead):
    r = run(lead, Site({"https://jobs.example/1": html("%PDF", "application/pdf")}))
    assert r.note == "The page isn't HTML."


def test_size_cap(lead):
    r = run(lead, Site({"https://jobs.example/1": html("a" * (2 * 1024 * 1024 + 1))}))
    assert r.text is None and r.note == "The page is too large."


@pytest.mark.parametrize("body", ["<p>Please sign in to continue</p>" + "x " * 400, "<p>too short</p>",
                                  "<p>Checking your browser. Captcha.</p>" + "y " * 400])
def test_junk_detected(lead, body):
    r = run(lead, Site({"https://jobs.example/1": html(body)}))
    assert r.text is None
    assert r.note == "The page needs a login or blocked the request — paste the posting instead."


def test_http_error_note(lead):
    r = run(lead, Site({"https://jobs.example/1": html("no", status=403)}))
    assert r.note == "The site blocked the request (HTTP 403)."


def test_robots_disallow(lead):
    site = Site({"https://jobs.example/1": html()}, robots="User-agent: *\nDisallow: /")
    r = run(lead, site)
    assert r.note == "The site's robots.txt disallows fetching this page." and site.seen == []


def test_network_error_note(lead):
    def boom(request):
        raise httpx.ConnectError("down", request=request)
    r = fetch_posting(lead, transport=httpx.MockTransport(boom), resolve=resolver())
    assert r.text is None and r.note.startswith("Couldn't reach the site")


def test_refresh_posting_stores_result(actx, make_lead, monkeypatch):
    lid = actx.leads.insert(make_lead(body="full", sources=["freelancer"]))
    refresh_posting(actx, lid)
    row = actx.assist.get(lid)
    assert row.fetch_tried and row.posting == "full" and row.posting_origin == "source"


def test_not_found_note(lead):
    r = run(lead, Site({"https://jobs.example/1": html("no", status=404)}))
    assert r.note == "The page wasn't found (HTTP 404) — it may have been taken down."
