"""One-click bid: the model writes the proposal and estimates hours; Prospector computes the money."""
from dataclasses import asdict, dataclass

from pydantic import BaseModel, Field, ValidationError

from prospector.assist import drafts
from prospector.assist.chat import ask, failure, history
from prospector.assist.pricing import Quote, bid_currency, in_currency, quote, tnd
from prospector.assist.usage import CapReached
from prospector.context import AppContext
from prospector.llm.client import LLMError, extract_json
from prospector.money import fmt, to_milli
from prospector.store.assist import Message

MIN_PROPOSAL = 100

INSTRUCTION = f"""Draft my bid for this lead. Answer ONLY with JSON:
{{"proposal": "<the text I paste into the platform's proposal box: at least {MIN_PROPOSAL} characters, aim for 600-1200; a one-line hook about their problem, my most relevant project with a concrete detail, how I'd approach it, one question for the client>",
 "estimate_hours": <realistic hours of work for me, a number>,
 "rationale": "<one or two sentences on the estimate and anything risky>"}}
Do not include prices; I compute them from my rate."""


class _Reply(BaseModel):
    proposal: str = Field(min_length=MIN_PROPOSAL)
    estimate_hours: float = Field(gt=0, le=2000)
    rationale: str = ""


@dataclass
class Bid:
    proposal: str
    rationale: str
    quote: Quote
    tnd_fair: int
    tnd_competitive: int

    def as_dict(self) -> dict:
        q = asdict(self.quote)  # carries "currency"; bids saved before it existed are USD
        return {"proposal": self.proposal, "rationale": self.rationale, **q,
                "tnd_fair": self.tnd_fair, "tnd_competitive": self.tnd_competitive}


def _parse(reply: str) -> _Reply:
    return _Reply.model_validate(extract_json(reply))


def draft_bid(ctx: AppContext, lead_id: int) -> Bid | Message:
    """A Bid (also saved and summarised in the chat), or the error Message that was stored."""
    messages = [*history(ctx, lead_id), {"role": "user", "content": INSTRUCTION}]
    try:
        reply = ask(ctx, lead_id, messages)
        try:
            parsed = _parse(reply)
        except (ValueError, ValidationError) as e:
            repair = (f"That reply was not usable ({type(e).__name__}: the proposal must be at least "
                      f"{MIN_PROPOSAL} characters and the answer valid JSON). Answer again with ONLY the JSON.")
            parsed = _parse(ask(ctx, lead_id, [*messages, {"role": "assistant", "content": reply},
                                               {"role": "user", "content": repair}]))
    except (CapReached, LLMError) as e:
        return failure(ctx, lead_id, e)
    except (ValueError, ValidationError):
        return failure(ctx, lead_id, LLMError("the model didn't return a usable bid; try again"))

    lead = ctx.leads.get(lead_id)
    code = bid_currency(lead.pay)
    per_usd = ctx.fx.rate(code)
    q = quote(parsed.estimate_hours, in_currency(ctx.profile.pricing, per_usd), lead.pay, code)
    priced = f"Priced in {code} from your USD rate at {per_usd:g} per USD." if code != "USD" else None
    rationale = " ".join(x for x in (parsed.rationale.strip(), priced, q.note) if x)
    tnd_rate = ctx.fx.rate("TND") / per_usd  # TND per unit of the bid's currency
    bid = Bid(parsed.proposal.strip(), rationale, q, tnd(q.fair, tnd_rate), tnd(q.competitive, tnd_rate))
    ctx.assist.set_bid(lead_id, bid.as_dict())
    ctx.assist.add(lead_id, "assistant",
                   f"Bid drafted: {fmt(to_milli(q.fair), code)} fair / {fmt(to_milli(q.competitive), code)} competitive, "
                   f"about {q.hours:g} hours, "
                   f"{q.delivery_days} day(s).\n\n{drafts.wrap(bid.proposal)}")
    return bid
