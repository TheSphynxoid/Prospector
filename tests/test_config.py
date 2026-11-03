from prospector import __version__
from prospector.config import Settings
from prospector.http import make_client


def test_settings_from_env(monkeypatch, tmp_path):
    for k, v in {"LLM_API_KEY": "k", "BRIDGE_SECRET": "s", "ACCESS_TEAM_DOMAIN": "t.cloudflareaccess.com",
                 "ACCESS_AUD": "aud", "PROFILE_PATH": str(tmp_path / "p.yaml")}.items():
        monkeypatch.setenv(k, v)
    s = Settings(_env_file=None)
    assert s.llm_daily_cap == 20
    assert s.llm_model == "glm-5.3-flash"
    assert s.llm_base_url == "https://opencode.ai/inference/go/openai/v1"


def test_client_user_agent():
    with make_client() as c:
        assert c.headers["User-Agent"].startswith(f"prospector/{__version__}")
        assert c.timeout.read == 20
