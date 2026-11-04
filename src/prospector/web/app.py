from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from prospector.context import AppContext
from prospector.web.auth import (allowed_hosts, make_access_middleware, make_host_middleware,
                                  make_same_origin_middleware)
from prospector.web.assist import make_assist_router
from prospector.web.dashboard import make_dashboard_router
from prospector.web.ingest import make_ingest_router
from prospector.web.settings import make_settings_router
from prospector.web.settings.cvs import make_cv_router
from prospector.web.work import make_work_router


def create_app(ctx: AppContext, lifespan=None) -> FastAPI:
    app = FastAPI(title="Prospector", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    # Registered last runs first: access check, then the same-origin check.
    app.middleware("http")(make_same_origin_middleware())
    app.middleware("http")(make_access_middleware(ctx.verifier))
    app.middleware("http")(make_host_middleware(allowed_hosts(ctx.settings)))  # outermost: runs first
    app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
    app.include_router(make_ingest_router(ctx.mail, ctx.settings.bridge_secret.get_secret_value().encode()))
    app.include_router(make_assist_router(ctx))  # before the dashboard's /lead/{id}/{action}
    app.include_router(make_work_router(ctx))
    app.include_router(make_cv_router(ctx))  # before settings' catch-all /settings/{area}
    app.include_router(make_dashboard_router(ctx))
    app.include_router(make_settings_router(ctx))

    @app.get("/healthz", response_class=PlainTextResponse)
    def healthz():
        return "ok"

    app.state.ctx = ctx
    return app
