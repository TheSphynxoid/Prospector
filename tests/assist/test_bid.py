from prospector.assist.bid import Bid, draft_bid
from prospector.assist.usage import used_today
from prospector.models import Pay

GOOD = {"proposal": "x" * 150, "estimate_hours": 10, "rationale": "Small API."}


def test_draft_bid_computes_money(actx, lid, fake):
    fake.replies = [GOOD]
    bid = draft_bid(actx, lid)
    assert isinstance(bid, Bid)
    assert (bid.quote.fair, bid.quote.competitive, bid.quote.delivery_days) == (250, 150, 2)
    assert (bid.tnd_fair, bid.tnd_competitive) == (750, 450)
    saved = actx.assist.get(lid).bid
    assert saved["proposal"] == "x" * 150 and saved["fair"] == 250 and saved["tnd_fair"] == 750
    last = actx.assist.messages(lid)[-1]
    assert last.role == "assistant" and last.content.startswith("Bid drafted:")
    # the bid instruction is sent but not stored in the chat
    assert "estimate_hours" in fake.calls[0]["messages"][-1]["content"]
    assert all("estimate_hours" not in m.content for m in actx.assist.messages(lid))


def test_draft_bid_repairs_invalid_json(actx, lid, fake):
    fake.replies = ["Sure! Here is a bid.", GOOD]
    assert isinstance(draft_bid(actx, lid), Bid)
    assert len(fake.calls) == 2 and used_today(actx) == 2


def test_draft_bid_retries_short_proposal(actx, lid, fake):
    fake.replies = [{**GOOD, "proposal": "too short"}, GOOD]
    bid = draft_bid(actx, lid)
    assert isinstance(bid, Bid) and len(bid.proposal) == 150 and len(fake.calls) == 2


def test_draft_bid_gives_up_after_one_repair(actx, lid, fake):
    fake.replies = ["nope", "still nope"]
    out = draft_bid(actx, lid)
    assert out.role == "error" and len(fake.calls) == 2


def test_draft_bid_ignores_model_prices(actx, lid, fake):
    fake.replies = [{**GOOD, "fair_price": 9999, "budget_warning": "made up"}]
    bid = draft_bid(actx, lid)
    assert bid.quote.fair == 250 and bid.quote.warning is None


def test_draft_bid_uses_lead_budget(actx, make_lead, fake):
    lid = actx.leads.insert(make_lead(canonical_url="https://e/2", pay=Pay(100, 200, "USD", "fixed")))
    fake.replies = [GOOD]
    assert draft_bid(actx, lid).quote.fair == 200


def test_draft_bid_adds_currency_note(actx, make_lead, fake):
    lid = actx.leads.insert(make_lead(canonical_url="https://e/3", pay=Pay(100, 200, "EUR", "fixed")))
    fake.replies = [GOOD]
    bid = draft_bid(actx, lid)
    assert "Client budget is in EUR" in bid.rationale


def test_draft_bid_cap(actx, lid, fake):
    actx.settings.assistant_daily_cap = 1
    fake.replies = ["bad json"]
    out = draft_bid(actx, lid)  # first call charged, repair refused by the cap
    assert out.role == "error" and "limit" in out.content and len(fake.calls) == 1
