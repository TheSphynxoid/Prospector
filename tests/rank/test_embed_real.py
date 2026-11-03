import numpy as np
import pytest

from prospector.rank.embed import FastEmbedder


@pytest.mark.slow
def test_fastembed_real(tmp_path_factory):
    emb = FastEmbedder("intfloat/multilingual-e5-base", tmp_path_factory.mktemp("models"))
    v = emb.embed(["Go backend engineer"], "passage")
    assert v.shape == (1, 768)
    assert np.linalg.norm(v[0]) == pytest.approx(1.0, abs=1e-3)
