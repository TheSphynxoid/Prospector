"""Dashboard-edited settings: DATA_DIR/settings.json, layered over env / .env.

pydantic-settings ranks keyword arguments above env and .env, so overrides are simply Settings(**overrides).
"""
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from prospector.config import EDITABLE, Settings

log = logging.getLogger(__name__)
FILENAME = "settings.json"
MIN_SECRET_LEN = 32
Origin = Literal["override", "env", "default"]


@dataclass
class LoadedSettings:
    settings: Settings
    overrides: dict[str, Any] = field(default_factory=dict)
    origins: dict[str, Origin] = field(default_factory=dict)
    rejected: str | None = None


def _errors(e: ValidationError) -> dict[str, str]:
    # Messages only, never input values: a rejected value may be a secret.
    return {str(err["loc"][0]) if err["loc"] else "_": err["msg"] for err in e.errors(include_input=False)}


def _origins(env_only: Settings, overrides: dict) -> dict[str, Origin]:
    return {name: "override" if name in overrides else ("env" if name in env_only.model_fields_set else "default")
            for name in Settings.model_fields}


def load_settings(env_file: str | None = ".env") -> LoadedSettings:
    env_only = Settings(_env_file=env_file)
    path = Path(env_only.data_dir) / FILENAME
    if not path.exists():
        return LoadedSettings(env_only, {}, _origins(env_only, {}))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not a JSON object")
        overrides = {k: v for k, v in raw.items() if k in EDITABLE}
        settings = Settings(_env_file=env_file, **overrides)
    except ValidationError as e:
        reason = "; ".join(f"{k}: {m}" for k, m in _errors(e).items())
        return _reject(path, env_only, reason)
    except (OSError, ValueError) as e:  # JSONDecodeError is a ValueError
        return _reject(path, env_only, f"{type(e).__name__}: {e}")
    return LoadedSettings(settings, overrides, _origins(env_only, overrides))


def _reject(path: Path, env_only: Settings, reason: str) -> LoadedSettings:
    log.error("ignoring %s: %s", path.name, reason)
    try:
        os.replace(path, path.with_name(FILENAME + ".rejected"))
    except OSError:
        log.exception("could not move %s aside", path.name)
    return LoadedSettings(env_only, {}, _origins(env_only, {}), rejected=reason)


def validate_overrides(env_file: str | None, overrides: dict) -> tuple[Settings | None, dict[str, str]]:
    from prospector.sources.registry import known_source_ids

    errors: dict[str, str] = {}
    try:
        settings = Settings(_env_file=env_file, **{k: v for k, v in overrides.items() if k in EDITABLE})
    except ValidationError as e:
        settings, errors = None, _errors(e)
    if "bridge_secret" in overrides and len(str(overrides["bridge_secret"] or "")) < MIN_SECRET_LEN:
        errors["bridge_secret"] = f"must be at least {MIN_SECRET_LEN} characters"
    unknown = [s for s in overrides.get("enabled_sources") or [] if s not in known_source_ids()]
    if unknown:
        errors["enabled_sources"] = f"unknown source: {', '.join(map(str, unknown))}"
    return (None, errors) if errors else (settings, {})


def save_overrides(data_dir: Path, overrides: dict) -> None:
    path = Path(data_dir) / FILENAME
    tmp = path.with_name(FILENAME + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(overrides, f, indent=2, sort_keys=True)
    os.replace(tmp, path)
