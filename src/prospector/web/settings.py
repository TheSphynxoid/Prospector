"""Settings page: edit overrides in DATA_DIR/settings.json, then restart to apply them."""
import html
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from prospector.config import EDITABLE, SECRETS, Settings
from prospector.context import AppContext
from prospector.settings_store import LoadedSettings, save_overrides, validate_overrides
from prospector.web.dashboard import templates


@dataclass(frozen=True)
class FieldInfo:
    name: str
    label: str
    kind: str = "text"  # text | url | secret | int | float | time | model
    help: str = ""


ACCESS_NOTE = "A wrong value only breaks the public address; Tailscale access keeps working."
KEYS = [
    FieldInfo("llm_api_key", "OpenCode Go API key", "secret"),
    FieldInfo("llm_base_url", "LLM endpoint", "url"),
    FieldInfo("telegram_token", "Telegram bot token", "secret", "From @BotFather."),
    FieldInfo("telegram_chat_id", "Telegram chat id", help="Your chat with the bot."),
    FieldInfo("bridge_url", "mail-bridge Worker URL", "url", "e.g. https://prospector-mail-bridge.<you>.workers.dev"),
    FieldInfo("bridge_secret", "BRIDGE_SECRET", "secret", "At least 32 characters; the Worker needs the same value."),
    FieldInfo("access_team_domain", "Cloudflare Access team domain", help=ACCESS_NOTE),
    FieldInfo("access_aud", "Cloudflare Access AUD tag", help=ACCESS_NOTE),
    FieldInfo("adzuna_app_id", "Adzuna app id"),
    FieldInfo("adzuna_app_key", "Adzuna app key", "secret"),
    FieldInfo("github_token", "GitHub token", "secret", "Read-only public scope is enough (bounty search)."),
    FieldInfo("dashboard_url", "Dashboard URL", "url", "Used for links in the digest."),
]
TUNING = [
    FieldInfo("llm_model", "LLM model", "model"),
    FieldInfo("llm_fallback_model", "Fallback model", "model"),
    FieldInfo("llm_daily_cap", "AI reviews per day", "int", "1–500."),
    FieldInfo("stage2_threshold", "Review threshold", "float", "Leads scoring at least this (0–1) get an AI review."),
    FieldInfo("digest_time", "Digest time", "time", "Africa/Tunis."),
]
_OPTIONAL_STR = {"telegram_chat_id", "bridge_url", "adzuna_app_id"}
assert {f.name for f in KEYS + TUNING} | {"enabled_sources"} == set(EDITABLE)


def _current(settings: Settings, name: str) -> Any:
    v = getattr(settings, name)
    return v.get_secret_value() if hasattr(v, "get_secret_value") else v


def _parse(info: FieldInfo, raw: str) -> Any:
    raw = raw.strip()
    if info.kind == "int":
        return int(raw)
    if info.kind == "float":
        return float(raw)
    if raw == "" and info.name in _OPTIONAL_STR:
        return None
    return raw


def merge_form(form, loaded: LoadedSettings) -> tuple[dict, dict[str, str]]:
    """New overrides from a posted settings form. A field only becomes an override when it changes."""
    new, errors = dict(loaded.overrides), {}
    for info in KEYS + TUNING:
        name = info.name
        if name in SECRETS:
            if form.get(f"clear_{name}"):
                new.pop(name, None)
            elif form.get(name):
                new[name] = form[name]
            continue
        if name not in form:
            continue
        try:
            value = _parse(info, form[name])
        except ValueError:
            errors[name] = "must be a number"
            continue
        if name in new or value != _current(loaded.settings, name):
            new[name] = value
    if form.get("enabled_sources_present"):
        chosen = form.getlist("enabled_sources")
        if "enabled_sources" in new or set(chosen) != set(loaded.settings.enabled_sources):
            new["enabled_sources"] = chosen
    return new, errors


def make_settings_router(ctx: AppContext) -> APIRouter:
    router = APIRouter()

    def loaded() -> LoadedSettings:
        if ctx.loaded is None:
            ctx.loaded = LoadedSettings(ctx.settings)
        return ctx.loaded

    def page(request: Request, status: int = 200, errors: dict | None = None, posted=None, notice: str = ""):
        from prospector.sources.registry import FACTORIES, known_source_ids

        known_source_ids()
        needs_creds = {sid for sid, f in FACTORIES.items() if f(ctx.settings, ctx.mail) is None}
        return templates.TemplateResponse(request, "settings.html", {
            "nav": "settings", "keys": KEYS, "tuning": TUNING, "secrets": SECRETS, "loaded": loaded(),
            "s": ctx.settings, "current": lambda n: _current(ctx.settings, n), "errors": errors or {},
            "posted": posted, "sources": sorted(FACTORIES), "needs_creds": needs_creds, "notice": notice,
        }, status_code=status)

    def apply(request: Request, new: dict):
        save_overrides(ctx.settings.data_dir, new)
        ctx.restart()
        return templates.TemplateResponse(request, "restarting.html", {"nav": "settings"})

    @router.get("/settings")
    def show(request: Request):
        return page(request)

    @router.post("/settings")
    async def save(request: Request):
        form = await request.form()
        new, errors = merge_form(form, loaded())
        _, invalid = validate_overrides(ctx.env_file, new)
        errors = invalid | errors  # unparseable numbers keep their own message
        if errors:
            return page(request, 400, errors, posted=form)
        if new == loaded().overrides:
            return page(request, notice="Nothing changed.")
        return apply(request, new)

    @router.post("/settings/reset/{name}")
    def reset(request: Request, name: str):
        if name not in loaded().overrides:
            return RedirectResponse("/settings", status_code=303)
        new = {k: v for k, v in loaded().overrides.items() if k != name}
        _, errors = validate_overrides(ctx.env_file, new)
        if errors:
            return page(request, 400, errors)
        return apply(request, new)

    @router.post("/settings/reveal-bridge-secret")
    def reveal():
        value = ctx.settings.bridge_secret.get_secret_value()
        return HTMLResponse(f'<code class="reveal">{html.escape(value)}</code>', headers={"Cache-Control": "no-store"})

    return router
