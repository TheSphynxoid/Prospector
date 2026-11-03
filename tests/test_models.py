from prospector.models import Kind, Lead, Remote, Status


def make_lead(**kw):
    base = dict(
        canonical_url="https://example.com/1", title="Go dev", company="Acme",
        kind=Kind.JOB, remote=Remote.YES, remote_region=None, locations=[],
        pay=None, languages=["en"], deadline=None, posted_at=None,
        body="text", content_hash="h", sources=["remotive"],
    )
    base.update(kw)
    return Lead(**base)


def test_lead_defaults():
    lead = make_lead()
    assert lead.status == Status.NEW
    assert lead.filter_reason is None
    assert lead.id is None


def test_kind_values():
    assert Kind("ai_training") is Kind.AI_TRAINING
