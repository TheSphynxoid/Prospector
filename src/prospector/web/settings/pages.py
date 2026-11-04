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


CARDS = [
    # name, title, fields, the fields that must be set, test route
    ("llm", "LLM", ["llm_api_key", "llm_base_url"], ["llm_api_key"], "/settings/test/llm"),
    ("telegram", "Telegram", ["telegram_token", "telegram_chat_id"], ["telegram_token", "telegram_chat_id"],
     "/settings/test/telegram"),
    ("email", "Email digest (mail-bridge Worker)", ["bridge_url", "bridge_secret"], ["bridge_url"],
     "/settings/test/email"),
    ("github", "GitHub", ["github_token"], ["github_token"], None),
    ("access", "Cloudflare Access", ["access_team_domain", "access_aud"], ["access_team_domain", "access_aud"], None),
]
STATE_LABEL = {"ok": "Connected", "failing": "Failing", "not_set": "Not set", "untested": "Not tested yet"}


def connection_cards(ctx: "AppContext") -> list[dict]:
    from prospector.store import conn_status

    s = ctx.settings
    cards = []
    for name, title, fields, required, test in CARDS:
        error, at = None, None
        if not all(getattr(s, f) for f in required):
            state = "not_set"
        elif name == "github":
            h = ctx.health.get("github_bounties")
            state = "untested" if h.last_run is None else ("failing" if h.last_error else "ok")
            error, at = h.last_error, h.last_run
        elif name == "access":
            state = "ok"
        else:
            rec = conn_status.get(ctx.kv, name)
            state = "untested" if rec is None else ("ok" if rec["ok"] else "failing")
            error, at = (rec or {}).get("error"), (rec or {}).get("at")
        cards.append({"name": name, "title": title, "fields": fields, "state": state, "label": STATE_LABEL[state],
                      "error": error, "at": at, "test": test})
    return cards


def source_rows(ctx: "AppContext") -> list[dict]:
    from prospector.sources.registry import FACTORIES, known_source_ids

    known_source_ids()
    running = {x.id for x in ctx.sources}
    rows = []
    for sid in sorted(FACTORIES):
        h = ctx.health.get(sid)
        state = ("paused" if h.paused else "failing" if h.consecutive_failures else "drift" if h.drift
                 else "ok" if h.last_ok else "never")
        rows.append({"id": sid, "h": h, "state": state, "enabled": sid in ctx.settings.enabled_sources,
                     "needs_creds": FACTORIES[sid](ctx.settings, ctx.mail) is None, "running": sid in running})
    return rows


def reload_profile(ctx: "AppContext", profile) -> bool:
    """Save and switch to the new profile without a restart; re-score leads in the background.
    Returns whether a re-score was queued (not when one is already running)."""
    from datetime import UTC, datetime

    from prospector.pipeline import rescore_all
    from prospector.profile.form import save_profile

    save_profile(ctx.settings.profile_path, profile)
    ctx.profile = profile
    ctx.profile_vecs = None  # rebuilt from the new skills and projects on next use
    status = ctx.kv.get("rescore_status") or {}
    if ctx.embedder is None or status.get("state") == "running":
        return False
    total = ctx.conn.execute("SELECT COUNT(*) FROM scores WHERE embedding IS NOT NULL").fetchone()[0]
    ctx.kv.set("rescore_status", {"state": "running", "count": total})
    ctx.run_background(lambda: rescore_all(ctx, datetime.now(UTC)))
    return True
