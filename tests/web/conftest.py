import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from prospector.config import Settings
from prospector.context import AppContext
from prospector.models import Kind
from prospector.profile.model import Profile, Project, Targets
from prospector.store.db import connect
from prospector.web.app import create_app
from prospector.web.auth import AccessVerifier

TEAM = "team.cloudflareaccess.com"
AUD = "aud-tag"
TAILNET = ("100.100.1.1", 1234)
OUTSIDE = ("172.17.0.1", 1234)


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def certs_transport(rsa_key):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_key.public_key()))
    jwk.update(kid="k1", alg="RS256", use="sig")

    def handler(request):
        assert request.url == f"https://{TEAM}/cdn-cgi/access/certs"
        return httpx.Response(200, json={"keys": [jwk]})
    return httpx.MockTransport(handler)


@pytest.fixture
def make_token(rsa_key):
    def _make(aud=AUD, exp_in=300):
        return jwt.encode({"aud": [aud], "iss": f"https://{TEAM}", "exp": int(time.time()) + exp_in,
                           "email": "owner@example.com"}, rsa_key, algorithm="RS256", headers={"kid": "k1"})
    return _make


@pytest.fixture
def ctx(certs_transport, tmp_path):
    settings = Settings(_env_file=None, llm_api_key="k", bridge_secret="s", access_team_domain=TEAM,
                        access_aud=AUD, profile_path=tmp_path / "p.yaml", data_dir=tmp_path)
    profile = Profile(skills={"go": 1}, projects=[Project(name="P", writeup="w")],
                      targets=Targets(kinds=list(Kind), regions=[]))
    http = httpx.Client(transport=certs_transport)
    return AppContext.create(settings, connect(":memory:"), profile, http,
                             verifier=AccessVerifier(TEAM, AUD, http))


@pytest.fixture
def app(ctx):
    return create_app(ctx)
