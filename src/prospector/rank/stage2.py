import logging
from datetime import date
from typing import Literal

from pydantic import BaseModel, ValidationError

from prospector.llm.client import LLMClient, LLMError, extract_json
from prospector.models import Lead
from prospector.profile.model import Profile
from prospector.store.kv import KV
from prospector.store.leads import LeadRepo
from prospector.store.scores import ScoreRepo

log = logging.getLogger(__name__)

SYSTEM = (
    "You screen job and gig leads for one candidate. Answer ONLY with JSON: "
    '{"verdict": "strong|maybe|weak", "fit_summary": "<=2 sentences", '
    '"lead_with_project": "<project name or null>", "red_flags": ["..."], '
    '"pay_estimate": "<string or null>"}'
)


class Stage2Result(BaseModel):
    verdict: Literal["strong", "maybe", "weak"]
    fit_summary: str
    lead_with_project: str | None = None
    red_flags: list[str] = []
    pay_estimate: str | None = None


def _user_prompt(lead: Lead, profile: Profile) -> str:
    projects = "\n".join(f"- {p.name}: {p.writeup}" for p in profile.projects)
    pay = f"{lead.pay.min}-{lead.pay.max} {lead.pay.currency}/{lead.pay.period}" if lead.pay else "not stated"
    return (
        f"CANDIDATE SKILLS: {', '.join(profile.skills)}\nCANDIDATE PROJECTS:\n{projects}\n\n"
        f"LEAD\nTitle: {lead.title}\nCompany: {lead.company or 'unknown'}\n"
        f"Location: {', '.join(lead.locations) or lead.remote.value}\nPay: {pay}\nKind: {lead.kind.value}\n"
        f"Description:\n{lead.body[:3000]}"
    )


def _cache_key(lead: Lead) -> str:
    return f"llm:{lead.content_hash}"


def review(lead: Lead, profile: Profile, client: LLMClient, kv: KV, session_id: str) -> Stage2Result | None:
    cached = kv.get(_cache_key(lead))
    if cached:
        return Stage2Result.model_validate(cached)
    user = _user_prompt(lead, profile)
    try:
        reply = client.complete(SYSTEM, user, session_id)
        try:
            result = Stage2Result.model_validate(extract_json(reply))
        except (ValueError, ValidationError):
            repair = f"{user}\n\nYour previous reply was invalid:\n{reply[:2000]}\n\n" \
                     "Return only valid JSON matching this schema: " + SYSTEM.split("JSON: ", 1)[1]
            result = Stage2Result.model_validate(extract_json(client.complete(SYSTEM, repair, session_id)))
    except LLMError as e:
        kv.set("llm_last_error", str(e))  # the setup checklist flags a rejected key
        log.warning("stage2 review failed for lead %s: %s", lead.id, e)
        return None
    except (ValueError, ValidationError) as e:
        log.warning("stage2 review failed for lead %s: %s", lead.id, e)
        return None
    kv.set("llm_last_error", None)
    kv.set(_cache_key(lead), result.model_dump())
    return result


def run_stage2(leads: LeadRepo, scores: ScoreRepo, kv: KV, client: LLMClient, profile: Profile,
               cap: int, threshold: float, today: date) -> int:
    """Review the best unreviewed leads within today's call budget; returns how many got a result."""
    used_key = f"llm_calls:{today.isoformat()}"
    used = kv.get(used_key, 0)
    if used >= cap:
        return 0
    reviewed = 0
    for lead_id in scores.top_unreviewed(threshold, (cap - used) * 3):
        if used >= cap:
            break
        lead = leads.get(lead_id)
        if lead is None:
            continue
        failed_key = f"llm_failed:{lead.content_hash}"
        if kv.get(failed_key) == today.isoformat():
            continue  # failed earlier today; retry tomorrow instead of draining the cap
        answered_before = client.answered
        result = review(lead, profile, client, kv, f"prospector-{today.isoformat()}")
        if client.answered > answered_before:  # only replies count; transport errors are free
            used += 1
            kv.set(used_key, used)
        if result is None:
            kv.set(failed_key, today.isoformat())
            continue
        scores.save_stage2(lead_id, result.model_dump())
        reviewed += 1
    return reviewed


