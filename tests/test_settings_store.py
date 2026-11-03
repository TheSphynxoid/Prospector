import json
import os

import pytest

from prospector.settings_store import load_settings, save_overrides, validate_overrides


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in {"DATA_DIR": str(tmp_path), "PROFILE_PATH": str(tmp_path / "p.yaml"), "LLM_API_KEY": "envkey",
                 "BRIDGE_SECRET": "e" * 32, "ACCESS_TEAM_DOMAIN": "team.example", "ACCESS_AUD": "aud"}.items():
        monkeypatch.setenv(k, v)
    return tmp_path


def write(path, data):
    (path / "settings.json").write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")


def test_override_beats_env(env):
    write(env, {"llm_api_key": "uikey", "llm_daily_cap": 5})
    ls = load_settings(env_file=None)
    assert ls.settings.llm_api_key.get_secret_value() == "uikey"
    assert ls.settings.llm_daily_cap == 5
    assert ls.origins["llm_api_key"] == "override"
    assert ls.origins["access_aud"] == "env"
    assert ls.origins["stage2_threshold"] == "default"


def test_no_file_is_env_only(env):
    ls = load_settings(env_file=None)
    assert ls.overrides == {} and ls.rejected is None
    assert ls.settings.llm_api_key.get_secret_value() == "envkey"


def test_unknown_override_key_ignored(env):
    write(env, {"data_dir": "/x", "bogus": 1, "llm_model": "m"})
    ls = load_settings(env_file=None)
    assert ls.settings.data_dir == env and ls.settings.llm_model == "m"
    assert ls.rejected is None and ls.overrides == {"llm_model": "m"}


def test_corrupt_file_rejected(env):
    write(env, "{not json")
    ls = load_settings(env_file=None)
    assert ls.rejected
    assert (env / "settings.json.rejected").exists() and not (env / "settings.json").exists()
    assert ls.settings.llm_api_key.get_secret_value() == "envkey"


def test_invalid_value_rejected(env):
    write(env, {"llm_daily_cap": "abc"})
    ls = load_settings(env_file=None)
    assert ls.rejected and "llm_daily_cap" in ls.rejected
    assert ls.settings.llm_daily_cap == 20


def test_validate_overrides_errors(env):
    settings, errors = validate_overrides(None, {"stage2_threshold": 2, "bridge_secret": "short",
                                                 "enabled_sources": ["nope"], "digest_time": "25:00"})
    assert settings is None
    assert set(errors) == {"stage2_threshold", "bridge_secret", "enabled_sources", "digest_time"}


def test_validate_overrides_ok(env):
    settings, errors = validate_overrides(None, {"llm_daily_cap": 30, "enabled_sources": ["hn"]})
    assert errors == {} and settings.llm_daily_cap == 30 and settings.enabled_sources == ["hn"]


def test_cap_range(env):
    assert set(validate_overrides(None, {"llm_daily_cap": 0})[1]) == {"llm_daily_cap"}
    assert set(validate_overrides(None, {"llm_daily_cap": 501})[1]) == {"llm_daily_cap"}


def test_save_atomic_and_private(env):
    save_overrides(env, {"llm_model": "m"})
    assert json.loads((env / "settings.json").read_text(encoding="utf-8")) == {"llm_model": "m"}
    assert not list(env.glob("*.tmp"))
    if os.name == "posix":
        assert (env / "settings.json").stat().st_mode & 0o777 == 0o600
