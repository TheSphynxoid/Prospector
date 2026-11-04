import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from prospector.config import Settings
from prospector.fx import Rates
from prospector.profile.model import Profile
from prospector.store.applications import ApplicationRepo
from prospector.store.assist import AssistRepo
from prospector.store.expiry import ExpiryRepo
from prospector.store.feedback import FeedbackRepo
from prospector.store.health import HealthRepo
from prospector.store.kv import KV
from prospector.store.leads import LeadRepo
from prospector.store.mail import MailRepo
from prospector.store.scores import ScoreRepo

if TYPE_CHECKING:
    from prospector.llm.client import LLMClient
    from prospector.rank.embed import Embedder
    from prospector.settings_store import LoadedSettings
    from prospector.sources.base import Source
    from prospector.web.auth import AccessVerifier


@dataclass
class AppContext:
    """Everything the web app, pipeline and scheduler share."""
    settings: Settings
    conn: sqlite3.Connection
    profile: Profile
    http: httpx.Client
    leads: LeadRepo
    scores: ScoreRepo
    feedback: FeedbackRepo
    health: HealthRepo
    mail: MailRepo
    kv: KV
    assist: AssistRepo
    expiry: ExpiryRepo
    fx: Rates
    apps: ApplicationRepo
    verifier: "AccessVerifier | None" = None
    embedder: "Embedder | None" = None
    llm: "LLMClient | None" = None
    assistant_llm: "LLMClient | None" = None  # own model and daily cap (see prospector.assist)
    sources: "list[Source]" = field(default_factory=list)
    profile_vecs: Any = None  # np.ndarray, computed lazily by the pipeline
    loaded: "LoadedSettings | None" = None  # where each setting came from; set by serve
    env_file: str | None = ".env"
    sched: Any = None  # the BackgroundScheduler, set by serve
    # serve swaps these for a real process restart and the scheduler's thread pool; tests keep them inline.
    restart: Callable[[], None] = lambda: None
    run_background: Callable[[Callable[[], None]], None] = lambda fn: fn()

    @classmethod
    def create(cls, settings: Settings, conn: sqlite3.Connection, profile: Profile, http: httpx.Client,
               **extra) -> "AppContext":
        return cls(settings=settings, conn=conn, profile=profile, http=http,
                   leads=LeadRepo(conn), scores=ScoreRepo(conn), feedback=FeedbackRepo(conn),
                   health=HealthRepo(conn), mail=MailRepo(conn), kv=KV(conn), assist=AssistRepo(conn), expiry=ExpiryRepo(conn),
                   fx=Rates(conn, tnd_override=settings.usd_tnd_rate), apps=ApplicationRepo(conn),
                   **extra)
