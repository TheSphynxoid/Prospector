import re

from prospector.models import Kind, RawLead

# Checked against the title, in order; AI training before contract so "AI training contractor" is AI work.
_RULES = [
    (Kind.PFE, re.compile(r"\bpfe\b|stage de fin d|fin d'[ée]tudes|end[- ]of[- ]stud", re.I)),
    (Kind.BOUNTY, re.compile(r"bounty", re.I)),
    (Kind.AI_TRAINING, re.compile(r"annotat|ai training|\brlhf\b|evaluate (ai|model)|ai tutor", re.I)),
    (Kind.CONTRACT, re.compile(r"freelance|\bcontract|contrat|\bmission\b", re.I)),
]


def detect_kind(raw: RawLead) -> Kind:
    if raw.kind_hint:
        return raw.kind_hint
    return next((kind for kind, pat in _RULES if pat.search(raw.title)), Kind.JOB)
