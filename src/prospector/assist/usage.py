"""The assistant's own daily call budget (separate from ranking's llm_calls)."""
from prospector.context import AppContext
from prospector.models import utcnow


class CapReached(Exception):
    def __init__(self, cap: int):
        super().__init__(f"Assistant limit reached for today ({cap}). Raise it in Settings.")


def _key() -> str:
    return f"assistant_calls:{utcnow().date().isoformat()}"  # same day boundary as llm_calls


def used_today(ctx: AppContext) -> int:
    return ctx.kv.get(_key(), 0)


def charge(ctx: AppContext) -> None:
    """Count one model call, or raise CapReached before it is made."""
    used, cap = used_today(ctx), ctx.settings.assistant_daily_cap
    if used >= cap:
        raise CapReached(cap)
    ctx.kv.set(_key(), used + 1)
