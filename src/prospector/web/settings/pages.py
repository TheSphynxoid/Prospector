"""The Settings areas: which fields live where, and the one-line status each shows on the hub."""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from prospector.context import AppContext


@dataclass(frozen=True)
class Area:
    key: str
    title: str
    blurb: str
    fields: list[str] = field(default_factory=list)

    @property
    def href(self) -> str:
        return f"/settings/{self.key}"


AREAS: list[Area] = [
    Area("connections", "Connections", "LLM, Telegram, email, GitHub and Cloudflare Access.",
         ["llm_api_key", "llm_base_url", "telegram_token", "telegram_chat_id", "bridge_url", "bridge_secret",
          "github_token", "access_team_domain", "access_aud", "dashboard_url", "adzuna_app_id", "adzuna_app_key"]),
    Area("sources", "Sources", "Where leads come from, and how each source is doing.", ["enabled_sources"]),
    Area("ai", "AI and limits", "Models, daily caps and the review threshold.",
         ["llm_model", "llm_fallback_model", "assistant_model", "llm_daily_cap", "assistant_daily_cap",
          "stage2_threshold"]),
    Area("profile", "Profile", "About you, skills, projects, interests and CVs."),
    Area("pricing", "Pricing and money", "Your rates and the TND exchange rate.", ["usd_tnd_rate"]),
    Area("schedule", "Schedule and Work", "Digest time, follow-ups and when leads expire.",
         ["digest_time", "followup_days", "expire_days_short", "expire_days_jobs", "expire_days_long"]),
]
BY_KEY = {a.key: a for a in AREAS}


def area_status(ctx: "AppContext", key: str) -> str:
    s, p = ctx.settings, ctx.profile
    if key == "connections":
        set_ = sum(bool(x) for x in (s.llm_api_key, s.telegram_token and s.telegram_chat_id, s.bridge_url,
                                     s.github_token, s.access_team_domain and s.access_aud))
        return f"{set_} of 5 set up"
    if key == "sources":
        failing = sum(1 for h in ctx.health.all() if h.source_id in s.enabled_sources and h.last_error)
        return f"{len(s.enabled_sources)} enabled" + (f" · {failing} failing" if failing else "")
    if key == "ai":
        return f"{s.llm_model} · {s.llm_daily_cap} reviews, {s.assistant_daily_cap} assistant messages a day"
    if key == "profile":
        return f"{len(p.skills)} skills · {len(p.projects)} projects"
    if key == "pricing":
        return f"${p.pricing.rate:g}/hour, lowest ${p.pricing.floor:g} · 1 USD = {ctx.fx.rate('TND'):g} TND"
    return f"Digest {s.digest_time} · follow up after {s.followup_days} days"
