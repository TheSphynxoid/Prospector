import logging
import shutil
from pathlib import Path

from prospector.__main__ import configure_logging, main

ROOT = Path(__file__).resolve().parents[1]


def env(monkeypatch, tmp_path):
    shutil.copy(ROOT / "profile.example.yaml", tmp_path / "profile.yaml")
    for k, v in {"LLM_API_KEY": "k", "BRIDGE_SECRET": "s", "ACCESS_TEAM_DOMAIN": "t", "ACCESS_AUD": "a",
                 "PROFILE_PATH": str(tmp_path / "profile.yaml"), "DATA_DIR": str(tmp_path)}.items():
        monkeypatch.setenv(k, v)


def test_digest_dry_run_prints_without_sending(monkeypatch, tmp_path, capsys):
    env(monkeypatch, tmp_path)
    assert main(["digest", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Prospector" in out and "0 new leads" in out
    assert (tmp_path / "prospector.db").exists()


def test_httpx_logging_quiet():
    configure_logging()
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
