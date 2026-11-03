from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from prospector.context import AppContext
from prospector.web.auth import make_access_middleware
from prospector.web.dashboard import make_dashboard_router
from prospector.web.ingest import make_ingest_router


def create_app(ctx: AppContext, lifespan=None) -> FastAPI:
    app = FastAPI(title="Prospector", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.middleware("http")(make_access_middleware(ctx.verifier))
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(make_ingest_router(ctx.mail, ctx.settings.bridge_secret.get_secret_value().encode()))
    app.include_router(make_dashboard_router(ctx))

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz():
        return "ok"

    app.state.ctx = ctx
    return app
