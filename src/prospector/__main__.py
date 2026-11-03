"""Prospector CLI: `python -m prospector <command>`."""
import argparse
import logging
import os
import sys
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from prospector.config import Settings
from prospector.context import AppContext
from prospector.http import make_client
from prospector.llm.client import LLMClient
from prospector.profile.model import load_profile
from prospector.settings_store import LoadedSettings, load_settings, start_with_fallback
from prospector.store.db import connect

log = logging.getLogger("prospector")


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs full request URLs at INFO; the Telegram URL contains the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


MIN_SECRET_LEN = 32


def check_secrets(settings: Settings) -> None:
    """Refuse to serve with a guessable HMAC secret (it guards /ingest/mail and the Worker's /digest)."""
    if len(settings.bridge_secret.get_secret_value()) < MIN_SECRET_LEN:
        raise SystemExit(f"BRIDGE_SECRET must be at least {MIN_SECRET_LEN} characters "
                         "(e.g. `openssl rand -hex 32`)")


def build_context(settings: Settings, with_embedder: bool = True, with_sources: bool = True) -> AppContext:
    from prospector.sources.registry import build_sources
    from prospector.web.auth import AccessVerifier

    data = Path(settings.data_dir)
    data.mkdir(parents=True, exist_ok=True)
    http = make_client()
    ctx = AppContext.create(
        settings, connect(data / "prospector.db"), load_profile(settings.profile_path), http,
        verifier=AccessVerifier(settings.access_team_domain, settings.access_aud, http),
        llm=LLMClient(settings.llm_base_url, settings.llm_api_key.get_secret_value(), settings.llm_model, http),
        assistant_llm=LLMClient(settings.llm_base_url, settings.llm_api_key.get_secret_value(),
                                settings.assistant_model or settings.llm_model, http),
    )
    if with_embedder:
        from prospector.rank.embed import FastEmbedder
        ctx.embedder = FastEmbedder(settings.embed_model, data / "models")
    if with_sources:
        ctx.sources = build_sources(settings, ctx.mail)
    return ctx


def background_runner(sched):
    """One-off jobs on the scheduler pool, never dropped as missed when the pool is busy (default grace is 1 s)."""
    return lambda fn: sched.add_job(fn, misfire_grace_time=None)


def _restart_soon() -> None:
    """Exit shortly after the response is sent; Docker (restart: unless-stopped) starts us again."""
    def bye():
        time.sleep(1)
        log.info("restarting to apply new settings")
        os._exit(0)
    threading.Thread(target=bye, daemon=True).start()


def cmd_serve(settings: Settings, args) -> int:
    import uvicorn

    from prospector.pipeline import select_model
    from prospector.scheduler import build_scheduler
    from prospector.web.app import create_app

    def start(s: Settings) -> AppContext:
        check_secrets(s)
        ctx = build_context(s)
        model = select_model(ctx.llm, s.llm_model, s.llm_fallback_model)
        if model is None:
            ctx.llm = None
        else:
            ctx.llm.model = model
        ctx.sched = build_scheduler(ctx)
        return ctx

    # A saved setting that breaks startup is set aside (banner on every page) instead of crash-looping.
    ctx, ctx_loaded = start_with_fallback(getattr(args, "loaded", None) or LoadedSettings(settings), ".env", start)
    sched = ctx.sched
    ctx.loaded = ctx_loaded
    ctx.restart = _restart_soon
    ctx.run_background = background_runner(sched)

    @asynccontextmanager
    async def lifespan(app):
        sched.start()
        yield
        sched.shutdown(wait=False)

    uvicorn.run(create_app(ctx, lifespan=lifespan), host=os.environ.get("HOST", "0.0.0.0"),
                port=int(os.environ.get("PORT", "8080")), proxy_headers=False, log_level="info")
    return 0


def cmd_run_source(settings: Settings, args) -> int:
    from prospector.pipeline import ingest

    ctx = build_context(settings)
    source = next((s for s in ctx.sources if s.id == args.source_id), None)
    if source is None:
        print(f"unknown or disabled source: {args.source_id}", file=sys.stderr)
        return 2
    print(ingest(ctx, source, datetime.now(UTC)))
    return 0


def cmd_stage2(settings: Settings, args) -> int:
    from prospector.pipeline import stage2

    print(f"reviewed {stage2(build_context(settings, with_embedder=False, with_sources=False), datetime.now(UTC).date())}")
    return 0


def cmd_digest(settings: Settings, args) -> int:
    from prospector.notify.run import send_digest
    from prospector.pipeline import digest_preview

    ctx = build_context(settings, with_embedder=False, with_sources=False)
    if args.dry_run:
        print("\n\n---\n\n".join(digest_preview(ctx, datetime.now(UTC))))
    else:
        send_digest(ctx, datetime.now(UTC))
    return 0


def cmd_check_llm(settings: Settings, args) -> int:
    ctx = build_context(settings, with_embedder=False, with_sources=False)
    models = ctx.llm.list_models()
    print(f"{len(models)} models available")
    for m in (settings.llm_model, settings.llm_fallback_model):
        print(f"  {m}: {'available' if m in models else 'MISSING'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="prospector")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("serve", help="run the dashboard and scheduler").set_defaults(fn=cmd_serve)
    rs = sub.add_parser("run-source", help="fetch one source now")
    rs.add_argument("source_id")
    rs.set_defaults(fn=cmd_run_source)
    sub.add_parser("stage2", help="run the LLM review now").set_defaults(fn=cmd_stage2)
    dg = sub.add_parser("digest", help="send (or preview) the digest now")
    dg.add_argument("--dry-run", action="store_true")
    dg.set_defaults(fn=cmd_digest)
    sub.add_parser("check-llm", help="list models and check the configured ones").set_defaults(fn=cmd_check_llm)
    args = parser.parse_args(argv)
    loaded = load_settings()
    args.loaded = loaded  # serve shows a banner when saved settings were rejected
    return args.fn(loaded.settings, args)


if __name__ == "__main__":
    sys.exit(main())
