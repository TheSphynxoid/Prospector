import pytest

from prospector.models import Kind, Pay, RawLead, Remote
from prospector.normalize.dedupe import is_duplicate
from prospector.normalize.kind import detect_kind
from prospector.normalize.lang import detect_languages
from prospector.normalize.normalize import normalize
from prospector.normalize.pay import parse_pay
from prospector.normalize.remote import parse_remote
from prospector.normalize.url import canonical_url


@pytest.mark.parametrize("a,b", [
    ("http://www.Remotive.com/jobs/1/?utm_source=x&ref=y#top", "https://remotive.com/jobs/1"),
    ("https://example.com/j?b=2&a=1&gclid=z", "https://example.com/j?a=1&b=2"),
    ("https://example.com/j/", "https://example.com/j"),
])
def test_canonical_url_equal(a, b):
    assert canonical_url(a) == canonical_url(b)


def test_canonical_url_keeps_meaningful_query():
    assert canonical_url("https://x.com/view?jobId=5") != canonical_url("https://x.com/view?jobId=6")


@pytest.mark.parametrize("text,expected", [
    ("3k–4k €/mois", Pay(3000, 4000, "EUR", "month")),
    ("1 500 TND", Pay(1500, 1500, "TND", None)),
    ("$40/hr", Pay(40, 40, "USD", "hour")),
    ("up to 120,000 USD", Pay(None, 120000, "USD", None)),
    ("€50,000 - €70,000 per year", Pay(50000, 70000, "EUR", "year")),
    ("2000 DT par mois", Pay(2000, 2000, "TND", "month")),
    ("250-750 USD fixed", Pay(250, 750, "USD", "fixed")),
    ("Competitive", None),
    (None, None),
    ("", None),
    ("€€€ ???", None),
])
def test_parse_pay(text, expected):
    assert parse_pay(text) == expected


@pytest.mark.parametrize("loc,title,body,expected", [
    ("Remote (EU only)", "Dev", "", (Remote.YES, "EU only")),
    ("Tunis, hybride", "Dev", "", (Remote.HYBRID, None)),
    ("Paris", "Dev", "", (Remote.NO, None)),
    (None, "Backend dev", "", (Remote.UNKNOWN, None)),
    (None, "Backend dev", "Ce poste est en télétravail complet.", (Remote.YES, None)),
    ("Remote - US", "Dev", "", (Remote.YES, "US")),
])
def test_parse_remote(loc, title, body, expected):
    assert parse_remote(loc, title, body) == expected


def raw(**kw):
    base = dict(source_id="s", external_id="1", url="https://x.com/1", title="Engineer", body="")
    base.update(kw)
    return RawLead(**base)


def test_detect_kind_pfe():
    assert detect_kind(raw(title="Stage PFE - Développeur Go")) is Kind.PFE


def test_detect_kind_hint_wins():
    assert detect_kind(raw(title="Senior Engineer", kind_hint=Kind.BOUNTY)) is Kind.BOUNTY


def test_detect_kind_default_job():
    assert detect_kind(raw(title="Senior Engineer")) is Kind.JOB


def test_detect_kind_contract_and_ai_training():
    assert detect_kind(raw(title="Freelance Go developer")) is Kind.CONTRACT
    assert detect_kind(raw(title="Coding expert for AI training")) is Kind.AI_TRAINING


def test_detect_languages_fr():
    assert detect_languages("Nous recherchons un développeur pour notre équipe dans le cadre de la croissance") == ["fr"]


def test_detect_languages_ar_first():
    assert detect_languages("نبحث عن مطور برمجيات للعمل في فريقنا")[0] == "ar"


def test_detect_languages_en():
    assert detect_languages("We are looking for a developer to join the team and the company") == ["en"]


def test_normalize_strips_html_and_hashes():
    lead = normalize(raw(body="<p>Hello&nbsp;<b>world</b></p>\n\n  again", company="Acme",
                         url="https://www.x.com/1?utm_source=a", location_text="Remote (EU only)"))
    assert lead.body == "Hello world\n\nagain"  # paragraph breaks kept (settings/UX spec §7)
    assert lead.canonical_url == "https://x.com/1"
    assert lead.sources == ["s"]
    assert lead.remote is Remote.YES and lead.remote_region == "EU only"
    assert len(lead.content_hash) == 64
    assert lead.locations == ["Remote (EU only)"]


def test_normalize_survives_bad_pay():
    assert normalize(raw(pay_text="€€€ ???")).pay is None


def test_dedupe_same_company_similar_title():
    a = normalize(raw(title="Senior Go Engineer", company="Acme Inc.", url="https://a.com/1"))
    b = normalize(raw(title="Senior Go Engineer (Remote)", company="ACME", url="https://b.com/9"))
    assert is_duplicate(a, b)


def test_dedupe_different_company():
    a = normalize(raw(title="Senior Go Engineer", company="Acme", url="https://a.com/1"))
    b = normalize(raw(title="Senior Go Engineer", company="Globex", url="https://b.com/1"))
    assert not is_duplicate(a, b)


def test_dedupe_same_url():
    a = normalize(raw(title="X", url="https://a.com/1?utm_source=z"))
    b = normalize(raw(title="Totally different", url="http://a.com/1/"))
    assert is_duplicate(a, b)


def test_clean_text_keep_lines():
    from prospector.normalize.normalize import clean_text
    assert clean_text("a  b\n\n\n\nc\t d", keep_lines=True) == "a b\n\nc d"
    assert clean_text("<p>x</p><p>y</p>", keep_lines=True) == "x\n\ny"
    assert clean_text("<p>Intro</p><ul><li>one</li><li>two</li></ul>", keep_lines=True) == "Intro\n\n- one\n- two"
    assert clean_text("a  b\n\nc") == "a b c"  # default still collapses everything


def test_normalize_keeps_body_lines_but_not_title():
    from prospector.models import RawLead
    from prospector.normalize.normalize import normalize
    lead = normalize(RawLead(source_id="x", external_id="1", url="https://e.com/1", title="Go\n  dev", company="A\nB",
                             body="<p>One</p><p>Two</p>"))
    assert lead.title == "Go dev" and lead.company == "A B" and lead.body == "One\n\nTwo"
