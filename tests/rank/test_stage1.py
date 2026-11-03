import hashlib
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from prospector.models import Kind, Pay, Remote
from prospector.profile.model import Profile, Project, Targets
from prospector.rank.embed import lead_text, profile_vectors
from prospector.rank.stage1 import score_stage1
from prospector.rank.weights import Weights, reweight

NOW = datetime(2026, 11, 3, tzinfo=UTC)


class FakeEmbedder:
    """Deterministic: identical text -> identical unit vector; different text -> ~orthogonal."""
    dim = 64

    def embed(self, texts, role):
        out = []
        for t in texts:
            seed = int.from_bytes(hashlib.sha256(t.encode()).digest()[:4], "little")
            v = np.random.default_rng(seed).standard_normal(self.dim)
            out.append(v / np.linalg.norm(v))
        return np.array(out, dtype=np.float32)


@pytest.fixture
def prof():
    return Profile(
        skills={"go": 1.0},
        projects=[Project(name="Room mapping", writeup="hotel room mapping engine in go")],
        targets=Targets(kinds=list(Kind), regions=["tunisia"]),
        boost_keywords={"golang": 1.0},
    )


def score(lead, prof, emb, vec=None, pos=None, neg=None, weights=None):
    pv = profile_vectors(prof, emb)
    v = vec if vec is not None else emb.embed([lead_text(lead)], "passage")[0]
    empty = np.zeros((0, emb.dim), dtype=np.float32)
    return score_stage1(lead, v, pv, pos if pos is not None else empty, neg if neg is not None else empty,
                        prof, weights or Weights(), NOW)


def test_matching_lead_scores_higher(make_lead, prof):
    emb = FakeEmbedder()
    match = make_lead(title="x", body="y")
    other = make_lead(title="Accountant", body="spreadsheets")
    match_vec = emb.embed(["hotel room mapping engine in go"], "query")[0]
    s_match, _ = score(match, prof, emb, vec=match_vec)
    s_other, _ = score(other, prof, emb)
    assert s_match > s_other


def test_breakdown_has_all_components(make_lead, prof):
    _, bd = score(make_lead(), prof, FakeEmbedder())
    assert set(bd) == {"sim", "keywords", "pay", "remote", "freshness", "feedback", "final"}
    assert all(0.0 <= v <= 1.0 for v in bd.values())


def test_feedback_neutral_without_examples(make_lead, prof):
    _, bd = score(make_lead(), prof, FakeEmbedder())
    assert bd["feedback"] == 0.5


def test_dismissed_neighbour_lowers_score(make_lead, prof):
    emb = FakeEmbedder()
    lead = make_lead(title="Some job")
    vec = emb.embed([lead_text(lead)], "passage")[0]
    base, _ = score(lead, prof, emb, vec=vec)
    lowered, bd = score(lead, prof, emb, vec=vec, neg=vec[None, :])
    assert lowered < base and bd["feedback"] < 0.5


def test_keyword_and_remote_and_freshness_components(make_lead, prof):
    emb = FakeEmbedder()
    _, bd = score(make_lead(title="Golang dev", remote=Remote.YES, posted_at=NOW), prof, emb)
    assert bd["keywords"] == pytest.approx(1 / 3) and bd["remote"] == 1.0 and bd["freshness"] == 1.0
    _, bd = score(make_lead(remote=Remote.NO, locations=["Tunis, Tunisia"], posted_at=NOW - timedelta(days=14)),
                  prof, emb)
    assert bd["remote"] == 1.0 and bd["freshness"] == pytest.approx(np.exp(-1))
    _, bd = score(make_lead(remote=Remote.NO, locations=["Berlin"]), prof, emb)
    assert bd["remote"] == 0.2 and bd["freshness"] == 0.5


def test_pay_component(make_lead, prof):
    emb = FakeEmbedder()
    assert score(make_lead(pay=None), prof, emb)[1]["pay"] == 0.5
    assert score(make_lead(pay=Pay(10, 20, "EUR", "hour")), prof, emb)[1]["pay"] == 1.0


def test_reweight_noop_below_10_rows():
    w = Weights()
    assert reweight(w, [({"sim": 1.0}, True)] * 9) == w


def test_reweight_moves_toward_positive_component_and_sums_to_one():
    comps = ["sim", "keywords", "pay", "remote", "freshness", "feedback"]
    pos = ({c: (1.0 if c == "sim" else 0.5) for c in comps}, True)
    neg = ({c: (0.0 if c == "sim" else 0.5) for c in comps}, False)
    w = reweight(Weights(), [pos] * 6 + [neg] * 6)
    assert w.sim > Weights().sim
    assert sum(w.as_dict().values()) == pytest.approx(1.0)
    assert all(0.05 <= v <= 0.60 for v in w.as_dict().values())
