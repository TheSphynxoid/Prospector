import re

from prospector.models import Lead, Pay, company_norm
from prospector.profile.model import Profile

_UNPAID = re.compile(r"\bunpaid\b|non[- ]r[ée]mun[ée]r[ée]|b[ée]n[ée]vole|\bvolunteer\b|equity[- ]only", re.I)


def pay_meets_min(pay: Pay | None, profile: Profile) -> bool | None:
    """True/False when a min-pay rule with the same currency+period applies, else None (unknown)."""
    if pay is None or pay.max is None:
        return None
    for rule in profile.filters.min_pay:
        if rule.currency == pay.currency and rule.period == pay.period:
            return pay.max >= rule.amount
    return None


def apply_hard_filters(lead: Lead, profile: Profile) -> str | None:
    """Reason the lead is filtered out, or None if it passes."""
    f = profile.filters
    cn = company_norm(lead.company)
    for blocked in f.blocked_companies:
        if cn and cn == company_norm(blocked):
            return f"blocked company: {blocked}"
    text = f"{lead.title}\n{lead.body}".lower()
    for kw in f.blocked_keywords:
        if re.search(rf"\b{re.escape(kw.lower())}\b", text):
            return f"blocked keyword: {kw}"
    if f.exclude_unpaid and _UNPAID.search(text):
        return "unpaid"
    if lead.kind not in profile.targets.kinds:
        return f"kind not targeted: {lead.kind.value}"
    if lead.languages and f.languages and not set(lead.languages) & set(f.languages):
        return f"language: {', '.join(lead.languages)}"
    if pay_meets_min(lead.pay, profile) is False:
        return "below min pay"
    return None
