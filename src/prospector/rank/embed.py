import logging
from pathlib import Path
from typing import Literal, Protocol

import numpy as np

from prospector.models import Lead
from prospector.profile.model import Profile

log = logging.getLogger(__name__)

FALLBACK_MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
Role = Literal["query", "passage"]


class Embedder(Protocol):
    def embed(self, texts: list[str], role: Role) -> np.ndarray: ...


def sim_range_for(model: str) -> tuple[float, float]:
    """Cosine range mapped to 0..1. e5 models compress cosines into a narrow high band."""
    return (0.75, 0.90) if "e5" in model else (0.25, 0.65)


class FastEmbedder:
    def __init__(self, model: str, cache_dir: Path):
        from fastembed import TextEmbedding

        supported = {m["model"] for m in TextEmbedding.list_supported_models()}
        if model not in supported:
            log.warning("embedding model %s not supported by fastembed; using %s", model, FALLBACK_MODEL)
            model = FALLBACK_MODEL
        self.model = model
        self.sim_range = sim_range_for(model)
        self._prefix = "e5" in model
        self._impl = TextEmbedding(model_name=model, cache_dir=str(cache_dir))

    def embed(self, texts: list[str], role: Role) -> np.ndarray:
        if self._prefix:
            texts = [f"{role}: {t}" for t in texts]
        vecs = np.array(list(self._impl.embed(texts)), dtype=np.float32)
        return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def lead_text(lead: Lead) -> str:
    return f"{lead.title}\n{lead.company or ''}\n{lead.body[:2000]}"


def profile_vectors(profile: Profile, embedder: Embedder) -> np.ndarray:
    texts = [p.writeup for p in profile.projects] + [", ".join(profile.skills)]
    return embedder.embed(texts, "query")
