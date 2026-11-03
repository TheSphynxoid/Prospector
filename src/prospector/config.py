"""Runtime settings, read from the environment / .env."""
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("/data")
    profile_path: Path
    dashboard_url: str = "https://prospector.thesphynx.net"

    llm_base_url: str = "https://opencode.ai/inference/go/openai/v1"
    llm_model: str = "glm-5.3-flash"
    llm_fallback_model: str = "qwen3.8-flash"
    llm_api_key: SecretStr
    llm_daily_cap: int = 20
    stage2_threshold: float = 0.55

    telegram_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    bridge_url: str | None = None
    bridge_secret: SecretStr

    access_team_domain: str
    access_aud: str

    adzuna_app_id: str | None = None
    adzuna_app_key: str | None = None
    github_token: SecretStr | None = None

    enabled_sources: list[str] = [
        "remotive", "remoteok", "himalayas", "arbeitnow", "adzuna",
        "hn", "github_bounties", "freelancer", "keejob", "alerts",
    ]
    embed_model: str = "intfloat/multilingual-e5-base"
