from rapidfuzz import fuzz

from prospector.models import Lead, company_norm


def is_duplicate(a: Lead, b: Lead) -> bool:
    if a.canonical_url == b.canonical_url:
        return True
    ca = company_norm(a.company)
    return bool(ca) and ca == company_norm(b.company) and fuzz.token_set_ratio(a.title, b.title) >= 90
