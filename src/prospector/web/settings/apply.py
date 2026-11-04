"""Saving settings: apply in place when possible, restart only for what is built once at startup."""
from typing import TYPE_CHECKING

from prospector.settings_store import load_settings, save_overrides, validate_overrides

if TYPE_CHECKING:
    from prospector.context import AppContext

# Read once when Prospector starts (LLM clients, sources, scheduler, Access verifier).
COLD: frozenset[str] = frozenset({
    "llm_api_key", "llm_base_url", "llm_model", "llm_fallback_model", "assistant_model", "enabled_sources",
    "digest_time", "access_team_domain", "access_aud", "github_token", "adzuna_app_id", "adzuna_app_key",
    "bridge_secret",   # the mail ingest route keeps the secret it started with
    "dashboard_url",   # the host check allows the dashboard's hostname, computed at startup
})


def _value(settings, name: str):
    v = getattr(settings, name)
    v = v.get_secret_value() if hasattr(v, "get_secret_value") else v
    return sorted(v) if isinstance(v, list) else (v or None)


def apply_overrides(ctx: "AppContext", new: dict) -> bool:
    """Save the overrides. Returns True when a restart was started, False when they were applied live.
    The caller has already validated `new`."""
    from prospector.config import EDITABLE

    validated, errors = validate_overrides(ctx.env_file, new)
    if errors or validated is None:
        raise ValueError(errors)
    # Only editable values change; paths, hosts and the like stay as the process started with them.
    candidate = ctx.settings.model_copy(update={k: getattr(validated, k) for k in EDITABLE})
    save_overrides(ctx.settings.data_dir, new)
    if any(_value(candidate, k) != _value(ctx.settings, k) for k in COLD):
        ctx.restart()
        return True
    ctx.settings = candidate
    ctx.loaded = load_settings(ctx.env_file)
    ctx.fx.tnd_override = candidate.usd_tnd_rate
    return False
