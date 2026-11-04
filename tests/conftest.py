import pytest

from prospector.models import Kind, Lead, Remote


@pytest.fixture
def make_lead():
    def _make(**kw):
        base = dict(
            canonical_url="https://example.com/1", title="Go dev", company="Acme",
            kind=Kind.JOB, remote=Remote.YES, remote_region=None, locations=[],
            pay=None, languages=["en"], deadline=None, posted_at=None,
            body="text", content_hash="h", sources=["remotive"],
        )
        base.update(kw)
        return Lead(**base)
    return _make


@pytest.fixture
def wctx(tmp_path):
    """An AppContext over an in-memory database, for the Work area (no web app)."""
    from tests.test_scheduler import make_ctx
    return make_ctx(tmp_path)
