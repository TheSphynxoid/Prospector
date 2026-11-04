"""Settings page: edit overrides in DATA_DIR/settings.json, then restart to apply them."""
import html
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from prospector.config import EDITABLE, SECRETS, Settings
from prospector.context import AppContext
from prospector.http import describe_error
from prospector.llm.client import LLMError
from prospector.notify.digest import build_digest, render_email
from prospector.notify.email import send_email_via_bridge
from prospector.notify.telegram import find_chats, send_telegram
from prospector.models import Kind
from prospector.profile.form import profile_from_rows, rows_from_form, rows_from_profile, save_profile
from prospector.settings_store import LoadedSettings, save_overrides, validate_overrides
from prospector.web.dashboard import templates
from prospector.web.settings.apply import COLD, apply_overrides
from prospector.web.settings.pages import AREAS, BY_KEY, area_status


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
    FieldInfo("telegram_chat_id", "Telegram chat id",
              help="Your chat with the bot. Save the token, send the bot any message, then use Find my chat ID."),
    FieldInfo("bridge_url", "mail-bridge Worker URL", "url", "e.g. https://prospector-mail-bridge.<you>.workers.dev"),
    FieldInfo("bridge_secret", "BRIDGE_SECRET", "secret", "At least 32 characters; the Worker needs the same value."),
    FieldInfo("access_team_domain", "Cloudflare Access team domain", help=ACCESS_NOTE),
    FieldInfo("access_aud", "Cloudflare Access AUD tag", help=ACCESS_NOTE),
    FieldInfo("adzuna_app_id", "Adzuna app id", help="Optional. Adzuna is paid beyond a small trial."),
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
    FieldInfo("assistant_model", "Assistant model", "model", "Blank uses the LLM model."),
    FieldInfo("assistant_daily_cap", "Assistant messages per day", "int", "1–2000."),
    FieldInfo("usd_tnd_rate", "USD → TND rate", "float", "Blank uses today's rate."),
    FieldInfo("followup_days", "Follow up after (days)", "int", "1–60."),
    FieldInfo("expire_days_short", "Expire gigs and bounties after (days)", "int", "Since posted, or first seen. 1–365."),
    FieldInfo("expire_days_jobs", "Expire jobs and contracts after (days)", "int", "1–365."),
    FieldInfo("expire_days_long", "Expire PFE and AI-training offers after (days)", "int", "1–365."),
]
_OPTIONAL_STR = {"telegram_chat_id", "bridge_url", "adzuna_app_id", "assistant_model"}
_OPTIONAL_FLOAT = {"usd_tnd_rate"}  # blank means automatic
assert {f.name for f in KEYS + TUNING} | {"enabled_sources"} == set(EDITABLE)


def _current(settings: Settings, name: str) -> Any:
    v = getattr(settings, name)
    return v.get_secret_value() if hasattr(v, "get_secret_value") else v


def _parse(info: FieldInfo, raw: str) -> Any:
    raw = raw.strip()
    if info.kind == "int":
        return int(raw)
    if info.kind == "float":
        return None if raw == "" and info.name in _OPTIONAL_FLOAT else float(raw)
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
        current = _current(loaded.settings, name)
        if name in _OPTIONAL_STR:  # .env passes "KEY=" as "", the form posts it back as None: same thing
            current = current or None
        if name in new or value != current:
            new[name] = value
    if form.get("enabled_sources_present"):
        chosen = form.getlist("enabled_sources")
        if "enabled_sources" in new or set(chosen) != set(loaded.settings.enabled_sources):
            new["enabled_sources"] = chosen
    return new, errors


def fx_line(rates) -> str:
    day, source, values = rates.today_summary()
    if day is None:
        return "No rates fetched yet; using built-in rates." + (
            f" (your override of {rates.tnd_override:g} TND is in use)" if rates.tnd_override else "")
    parts = " · ".join(f"{values[c]:g} {c}" for c in ("TND", "EUR", "GBP") if c in values)
    line = f"1 USD = {parts} — {source}, {day.day} {day.strftime('%b')}"
    line += " — rates are out of date, check Sources." if rates.stale() else ""
    return line + (f" (your override of {rates.tnd_override:g} TND is in use)" if rates.tnd_override else "")


def make_settings_router(ctx: AppContext) -> APIRouter:
    router = APIRouter()

    def loaded() -> LoadedSettings:
        if ctx.loaded is None:
            ctx.loaded = LoadedSettings(ctx.settings)
        return ctx.loaded

    FIELDS = {f.name: f for f in KEYS + TUNING}

    def page(request: Request, area_key: str = "", status: int = 200, errors: dict | None = None, posted=None,
             notice: str = "", prow: dict | None = None, profile_error: str = "", extra: dict | None = None):
        from prospector.sources.registry import FACTORIES, known_source_ids

        known_source_ids()
        area = BY_KEY.get(area_key)
        if area is None:
            return templates.TemplateResponse(request, "settings/hub.html", {
                "nav": "settings", "area": None, "areas": AREAS, "notice": notice, "errors": {},
                "statuses": {a.key: area_status(ctx, a.key) for a in AREAS}}, status_code=status)
        needs_creds = {sid for sid, f in FACTORIES.items() if f(ctx.settings, ctx.mail) is None}
        name = {"profile": "settings/profile.html", "pricing": "settings/pricing.html"}.get(area.key, "settings/area.html")
        return templates.TemplateResponse(request, name, {
            "nav": "settings", "area": area, "areas": AREAS, "area_fields": [FIELDS[n] for n in area.fields if n in FIELDS],
            "cold": COLD, "secrets": SECRETS, "loaded": loaded(),
            "s": ctx.settings, "current": lambda n: _current(ctx.settings, n), "errors": errors or {},
            "posted": posted, "sources": sorted(FACTORIES), "needs_creds": needs_creds, "notice": notice,
            "prow": prow or rows_from_profile(ctx.profile), "profile_error": profile_error, "kinds": list(Kind),
            "periods": ["hour", "day", "month", "year", "fixed"], "rescore": ctx.kv.get("rescore_status"),
            "running_sources": [x.id for x in ctx.sources], "fx_line": fx_line(ctx.fx),
            "pricing": ctx.profile.pricing.model_dump(), **(extra or {}),
        }, status_code=status)

    def apply(request: Request, new: dict, area_key: str):
        if apply_overrides(ctx, new):
            return templates.TemplateResponse(request, "restarting.html", {"nav": "settings"})
        return RedirectResponse(f"/settings/{area_key}?saved=1" if area_key in BY_KEY else "/settings?saved=1",
                                status_code=303)

    @router.get("/settings")
    def show(request: Request, saved: str = ""):
        return page(request, notice="Saved." if saved else "")

    @router.post("/settings")
    async def save(request: Request):
        form = await request.form()
        new, errors = merge_form(form, loaded())
        _, invalid = validate_overrides(ctx.env_file, new)
        errors = invalid | errors  # unparseable numbers keep their own message
        # Show errors on the page that has the field; a form from one page names its area.
        area_key = next((a.key for e in errors for a in AREAS if e in a.fields), "") or form.get("_area", "")
        if errors:
            return page(request, area_key, 400, errors, posted=form)
        if new == loaded().overrides:
            return page(request, area_key, notice="Nothing changed.")
        return apply(request, new, area_key)

    @router.post("/settings/reset/{name}")
    def reset(request: Request, name: str):
        area_key = next((a.key for a in AREAS if name in a.fields), "")
        if name not in loaded().overrides:
            return RedirectResponse(f"/settings/{area_key}" if area_key else "/settings", status_code=303)
        new = {k: v for k, v in loaded().overrides.items() if k != name}
        _, errors = validate_overrides(ctx.env_file, new)
        if errors:
            return page(request, area_key, 400, errors)
        return apply(request, new, area_key)

    @router.post("/settings/pricing")
    async def save_pricing(request: Request):
        from prospector.profile.model import Pricing

        form = await request.form()
        errors: dict[str, str] = {}
        try:
            pricing = Pricing(rate=form.get("rate", ""), floor=form.get("floor", ""),
                              hours_per_day=form.get("hours_per_day", ""))
        except ValidationError as e:
            pricing = None
            for err in e.errors(include_input=False):
                key = str(err["loc"][0]) if err["loc"] else "floor"
                errors[key] = err["msg"].removeprefix("Value error, ")
        new, form_errors = merge_form(form, loaded())
        _, invalid = validate_overrides(ctx.env_file, new)
        errors |= invalid | form_errors
        if errors:
            return page(request, "pricing", 400, errors, posted=form)
        if pricing != ctx.profile.pricing:
            profile = ctx.profile.model_copy(update={"pricing": pricing})
            save_profile(ctx.settings.profile_path, profile)
            ctx.profile = profile
        if new != loaded().overrides:
            return apply(request, new, "pricing")
        return RedirectResponse("/settings/pricing?saved=1", status_code=303)

    @router.post("/settings/profile")
    async def save_profile_form(request: Request):
        rows = rows_from_form(await request.form())
        try:
            profile = profile_from_rows(rows)
        except ValidationError as e:
            err = e.errors(include_input=False)[0]
            return page(request, "profile", 400, prow=rows,
                        profile_error=f"{'.'.join(map(str, err['loc']))}: {err['msg']}")
        except ValueError as e:
            return page(request, "profile", 400, prow=rows, profile_error=str(e))
        save_profile(ctx.settings.profile_path, profile)
        ctx.restart()
        return templates.TemplateResponse(request, "restarting.html", {"nav": "settings"})

    def rescore_fragment(status: dict | None) -> HTMLResponse:
        if status and status.get("state") == "running":
            return HTMLResponse('<span id="rescore-status" class="muted" hx-get="/settings/rescore-status" '
                                f'hx-trigger="every 2s" hx-swap="outerHTML">Re-scoring {status["count"]} leads…</span>')
        if status:
            return HTMLResponse(f'<span id="rescore-status" class="test-ok">Re-scored {status["count"]} leads ✓</span>')
        return HTMLResponse('<span id="rescore-status"></span>')

    @router.post("/settings/rescore")
    def rescore():
        from prospector.pipeline import rescore_all

        if ctx.embedder is None:
            return HTMLResponse('<span id="rescore-status" class="test-err">The embedding model is not loaded.</span>')
        total = ctx.conn.execute("SELECT COUNT(*) FROM scores WHERE embedding IS NOT NULL").fetchone()[0]
        ctx.kv.set("rescore_status", {"state": "running", "count": total})  # before queueing: no stale "done"
        ctx.run_background(lambda: rescore_all(ctx, datetime.now(UTC)))
        return rescore_fragment({"state": "running", "count": total})

    @router.get("/settings/rescore-status")
    def rescore_status():
        return rescore_fragment(ctx.kv.get("rescore_status"))

    def result(ok: bool, text: str, extra: str = "") -> HTMLResponse:
        return HTMLResponse(f'<span class="{"test-ok" if ok else "test-err"}">{html.escape(text)}</span>{extra}')

    @router.post("/settings/test/llm")
    def test_llm():
        if ctx.llm is None:
            return result(False, "LLM client not available (no models matched at startup, or no key).")
        try:
            models = ctx.llm.list_models()
        except LLMError as e:
            ctx.kv.set("llm_last_error", str(e))
            return result(False, str(e))
        ctx.kv.set("llm_last_error", None)
        s = ctx.settings
        status = ", ".join(f"{m}: {'available' if m in models else 'missing'}" for m in (s.llm_model, s.llm_fallback_model))
        options = "".join(f'<option value="{html.escape(m)}">' for m in models)
        return result(True, f"{len(models)} models · {status}",
                      f'<datalist id="llm-models" hx-swap-oob="true">{options}</datalist>')

    @router.post("/settings/test/telegram")
    def test_telegram():
        s = ctx.settings
        if not (s.telegram_token and s.telegram_chat_id):
            return result(False, "Telegram token or chat id not set.")
        try:
            send_telegram(ctx.http, s.telegram_token.get_secret_value(), s.telegram_chat_id, "Prospector test message ✓")
        except httpx.HTTPError as e:
            return result(False, describe_error(e))
        return result(True, "Sent — check Telegram.")

    @router.post("/settings/telegram/find-chat")
    def find_chat():
        s = ctx.settings
        if not s.telegram_token:
            return result(False, "Save the bot token first.")
        try:
            chats = find_chats(ctx.http, s.telegram_token.get_secret_value())
        except httpx.HTTPError as e:
            return result(False, describe_error(e))
        if not chats:
            return result(False, "No messages yet: send your bot a message in Telegram, then try again.")
        buttons = "".join(
            f' <button type="button" class="btn btn-sm" data-fill="#in-telegram_chat_id" data-value="{html.escape(cid)}">'
            f'Use {html.escape(cid)} · {html.escape(name)}</button>' for cid, name in chats)
        return result(True, "Pick your chat, then save:", buttons)

    @router.post("/settings/test/email")
    def test_email():
        s = ctx.settings
        if not s.bridge_url:
            return result(False, "Worker URL not set.")
        subject, text, body = render_email(build_digest(ctx.leads, ctx.health, ctx.kv, datetime.now(UTC), s.dashboard_url, ctx.expiry, ctx.apps))
        try:
            send_email_via_bridge(ctx.http, s.bridge_url, s.bridge_secret.get_secret_value().encode(),
                                  f"[test] {subject}", text, body)
        except httpx.HTTPError as e:
            return result(False, describe_error(e))
        return result(True, "Sent the current digest — check your inbox.")

    @router.post("/settings/test/source/{source_id}")
    def test_source(source_id: str):
        from prospector.pipeline import ingest

        source = next((x for x in ctx.sources if x.id == source_id), None)
        if source is None:
            raise HTTPException(404)
        ctx.run_background(lambda: ingest(ctx, source, datetime.now(UTC)))
        return result(True, "Queued — results appear on the Sources page in a minute.")

    @router.post("/settings/reveal-bridge-secret")
    def reveal():
        value = ctx.settings.bridge_secret.get_secret_value()
        return HTMLResponse(f'<code class="reveal">{html.escape(value)}</code>', headers={"Cache-Control": "no-store"})

    # Last, so the fixed /settings/... routes above win.
    @router.get("/settings/{area_key}")
    def show_area(request: Request, area_key: str, saved: str = ""):
        if area_key not in BY_KEY:
            raise HTTPException(404)
        return page(request, area_key, notice="Saved." if saved else "")

    return router
