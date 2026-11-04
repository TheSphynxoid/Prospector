"""Runtime settings, read from the environment / .env (overridable from the dashboard, see settings_store)."""
import re
from datetime import time
from pathlib import Path

import httpx
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Fields the dashboard may override, in the order the settings page shows them.
EDITABLE: tuple[str, ...] = (
    "llm_api_key", "llm_base_url", "telegram_token", "telegram_chat_id", "bridge_url", "bridge_secret",
    "access_team_domain", "access_aud", "adzuna_app_id", "adzuna_app_key", "github_token", "dashboard_url",
    "llm_model", "llm_fallback_model", "llm_daily_cap", "stage2_threshold", "enabled_sources", "digest_time",
    "assistant_model", "assistant_daily_cap", "usd_tnd_rate", "followup_days", "expire_days_short", "expire_days_jobs", "expire_days_long",
)
SECRETS: frozenset[str] = frozenset({"llm_api_key", "telegram_token", "bridge_secret", "adzuna_app_key", "github_token"})
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def parse_hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    data_dir: Path = Path("/data")
    profile_path: Path
    dashboard_url: str = "https://prospector.thesphynx.net"

    llm_base_url: str = "https://opencode.ai/inference/go/openai/v1"
    llm_model: str = "glm-5.3-flash"
    llm_fallback_model: str = "qwen3.8-flash"
    llm_api_key: SecretStr
    llm_daily_cap: int = Field(20, ge=1, le=500)
    stage2_threshold: float = Field(0.55, ge=0, le=1)
    assistant_model: str | None = None  # blank: llm_model
    assistant_daily_cap: int = Field(100, ge=1, le=2000)
    usd_tnd_rate: float | None = Field(None, gt=0, le=100)  # manual override; None = today's fetched rate
    followup_days: int = Field(7, ge=1, le=60)  # days after applying (or following up) before a reminder
    # Leads older than this (days since posted, else first seen) expire: gigs/bounties, jobs/contracts, PFE/AI training.
    expire_days_short: int = Field(14, ge=1, le=365)
    expire_days_jobs: int = Field(45, ge=1, le=365)
    expire_days_long: int = Field(60, ge=1, le=365)

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
        "remotive", "remoteok", "himalayas", "arbeitnow",  # adzuna: paid, opt in from Settings
        "hn", "github_bounties", "freelancer", "keejob", "alerts",
    ]
    embed_model: str = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
    digest_time: str = "08:00"  # HH:MM, Africa/Tunis

    # Not editable from the dashboard: hostnames the app answers to (DNS-rebinding guard, see web.app).
    tailscale_ip: str | None = None
    allowed_hosts: list[str] = []

    @field_validator("llm_base_url", "bridge_url", "dashboard_url")
    @classmethod
    def _http_url(cls, v: str | None) -> str | None:
        # Checked the way httpx will parse it later, so a saved value cannot crash startup.
        if v is None or v == "":
            return v
        try:
            url = httpx.URL(v)
        except (httpx.InvalidURL, TypeError) as e:
            raise ValueError(f"not a valid URL ({e.__class__.__name__})") from None
        if url.scheme not in ("http", "https") or not url.host:
            raise ValueError("must be an http(s) URL with a host")
        return v

    @field_validator("digest_time")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("use HH:MM, e.g. 08:00")
        return v
