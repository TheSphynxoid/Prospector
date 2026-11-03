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
