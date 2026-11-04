import logging

from prospector.assist.context import system_prompt
from prospector.assist.usage import CapReached, charge
from prospector.context import AppContext
from prospector.store import conn_status
from prospector.llm.client import LLMError
from prospector.store.assist import Message

log = logging.getLogger(__name__)
HISTORY = 20


def session_id(lead_id: int) -> str:
    return f"assist-{lead_id}"


def history(ctx: AppContext, lead_id: int) -> list[dict]:
    return [{"role": m.role, "content": m.content} for m in ctx.assist.recent(lead_id, HISTORY)]


def ask(ctx: AppContext, lead_id: int, messages: list[dict]) -> str:
    """One charged model call. Raises CapReached or LLMError; records a rejected key like stage 2."""
    if ctx.assistant_llm is None:
        raise LLMError("the assistant has no LLM configured")
    charge(ctx)
    try:
        reply = ctx.assistant_llm.chat(system_prompt(ctx, lead_id), messages, session_id(lead_id))
    except LLMError as e:
        conn_status.record(ctx.kv, "llm", False, str(e))
        raise
    conn_status.record(ctx.kv, "llm", True)
    return reply


def failure(ctx: AppContext, lead_id: int, e: Exception) -> Message:
    text = str(e) if isinstance(e, CapReached) else f"The assistant couldn't answer: {e}"
    log.warning("assistant failed for lead %s: %s", lead_id, e)
    return ctx.assist.add(lead_id, "error", text)


def send(ctx: AppContext, lead_id: int, text: str) -> list[Message]:
    """Store the owner's message, ask the model, store its reply (or an error). Returns the new messages."""
    past = history(ctx, lead_id)
    user = ctx.assist.add(lead_id, "user", text)
    try:
        reply = ask(ctx, lead_id, [*past, {"role": "user", "content": text}])
    except (CapReached, LLMError) as e:
        return [user, failure(ctx, lead_id, e)]
    return [user, ctx.assist.add(lead_id, "assistant", reply)]
