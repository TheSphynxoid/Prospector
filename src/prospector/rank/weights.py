from dataclasses import asdict, dataclass

import numpy as np

from prospector.store.kv import KV

COMPONENTS = ("sim", "keywords", "pay", "remote", "freshness", "feedback")
_MIN_ROWS, _STEP, _LO, _HI = 10, 0.02, 0.05, 0.60


@dataclass
class Weights:
    sim: float = 0.40
    keywords: float = 0.20
    pay: float = 0.10
    remote: float = 0.10
    freshness: float = 0.10
    feedback: float = 0.10

    def as_dict(self) -> dict[str, float]:
        return asdict(self)

    @classmethod
    def load(cls, kv: KV) -> "Weights":
        return cls(**kv.get("weights", {}))

    def save(self, kv: KV) -> None:
        kv.set("weights", self.as_dict())


def reweight(weights: Weights, rows: list[tuple[dict, bool]]) -> Weights:
    """Nudge each component weight toward what separates liked from dismissed leads."""
    if len(rows) < _MIN_ROWS:
        return weights
    new = weights.as_dict()
    for c in COMPONENTS:
        pos = [bd[c] for bd, p in rows if p and c in bd]
        neg = [bd[c] for bd, p in rows if not p and c in bd]
        if pos and neg:
            diff = float(np.mean(pos) - np.mean(neg))
            new[c] = min(_HI, max(_LO, new[c] + _STEP * float(np.sign(diff))))
    total = sum(new.values())
    return Weights(**{c: v / total for c, v in new.items()})
