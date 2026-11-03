from datetime import datetime

import numpy as np

from prospector.models import Lead, Remote
from prospector.profile.filters import pay_meets_min
from prospector.profile.model import Profile
from prospector.rank.weights import Weights


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def _max_cos(vec: np.ndarray, mat: np.ndarray) -> float | None:
    if mat.size == 0:
        return None
    return float(np.max(mat @ vec))


def score_stage1(lead: Lead, lead_vec: np.ndarray, profile_vecs: np.ndarray, pos_vecs: np.ndarray,
                 neg_vecs: np.ndarray, profile: Profile, weights: Weights, now: datetime,
                 sim_range: tuple[float, float] = (0.25, 0.65)) -> tuple[float, dict[str, float]]:
    lo, hi = sim_range
    sim = _clamp(((_max_cos(lead_vec, profile_vecs) or 0.0) - lo) / (hi - lo))

    # One line padded with spaces, so " go " also matches list items and words at line ends.
    text = " " + " ".join(f"{lead.title}\n{lead.body}".lower().split()) + " "
    keywords = _clamp(sum(w for kw, w in profile.boost_keywords.items() if kw.lower() in text) / 3)

    meets = pay_meets_min(lead.pay, profile)
    pay = 0.5 if lead.pay is None else (0.0 if meets is False else 1.0)

    if lead.remote is Remote.YES:
        remote = 1.0
    elif lead.remote is Remote.HYBRID:
        remote = 0.6
    elif lead.remote is Remote.UNKNOWN:
        remote = 0.5
    else:
        locs = " ".join(lead.locations).lower()
        remote = 1.0 if any(r.lower() in locs for r in profile.targets.regions) else 0.2

    if lead.posted_at is None:
        freshness = 0.5
    else:
        age_days = max(0.0, (now - lead.posted_at).total_seconds() / 86400)
        freshness = float(np.exp(-age_days / 14))

    pos, neg = _max_cos(lead_vec, pos_vecs), _max_cos(lead_vec, neg_vecs)
    if pos is None and neg is None:
        feedback = 0.5
    else:
        feedback = _clamp(0.5 + ((pos or 0.0) - (neg or 0.0)) / 2)

    parts = {"sim": sim, "keywords": keywords, "pay": pay, "remote": remote,
             "freshness": freshness, "feedback": feedback}
    w = weights.as_dict()
    final = _clamp(sum(w[k] * v for k, v in parts.items()))
    return final, {**parts, "final": final}
