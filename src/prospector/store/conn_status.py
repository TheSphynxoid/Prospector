"""How each connection did the last time it was tested or used (LLM, Telegram, email)."""
from prospector.store.db import now_iso
from prospector.store.kv import KV

NAMES = ("llm", "telegram", "email", "github", "access", "search")


def record(kv: KV, name: str, ok: bool, error: str | None = None) -> None:
    kv.set(f"conn:{name}", {"ok": ok, "at": now_iso(), "error": None if ok else (error or "failed")[:300]})
    if name == "llm":  # the setup checklist reads this one
        kv.set("llm_last_error", None if ok else (error or "failed"))


def get(kv: KV, name: str) -> dict | None:
    return kv.get(f"conn:{name}")
