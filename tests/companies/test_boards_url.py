import pytest

from prospector.companies.boards import parse_board_url


@pytest.mark.parametrize("url,out", [
    ("https://jobs.lever.co/certik/478ab0cd", ("lever", "certik")),
    ("https://boards.greenhouse.io/cloudflare/jobs/123", ("greenhouse", "cloudflare")),
    ("https://job-boards.greenhouse.io/Anthropic", ("greenhouse", "anthropic")),
    ("https://boards-api.greenhouse.io/v1/boards/stripe/jobs", ("greenhouse", "stripe")),
    ("https://boards.greenhouse.io/embed/job_board?for=gitlab", ("greenhouse", "gitlab")),
    ("http://www.jobs.ashbyhq.com/sensor-tower/b6505a02", ("ashby", "sensor-tower")),
    ("https://jobs.ashbyhq.com/ramp", ("ashby", "ramp")),
    ("https://greenhouse.io.evil.com/x", None), ("https://lever.co/acme", None),
    ("https://example.com/jobs.lever.co/acme", None), ("not a url", None), ("https://jobs.lever.co/", None),
    ("https://boards.greenhouse.io/embed/job_board", None), ("https://boards-api.greenhouse.io/v1/boards/", None),
    ("ftp://jobs.lever.co/acme", None), ("https://jobs.lever.co.evil.com/acme", None),
])
def test_parse_board_url(url, out):
    assert parse_board_url(url) == out


def test_parse_board_url_noise():
    assert parse_board_url("https://jobs.lever.co/acme/123?lever-source=x#apply") == ("lever", "acme")
    assert parse_board_url("  https://JOBS.ASHBYHQ.COM/Acme/?utm_source=x  ") == ("ashby", "acme")
    assert parse_board_url("https://jobs.lever.co/acme%2Fevil") is None
