import sqlite3
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import httpx

from prospector.config import Settings
from prospector.profile.model import Profile
from prospector.store.feedback import FeedbackRepo
from prospector.store.health import HealthRepo
from prospector.store.kv import KV
from prospector.store.leads import LeadRepo
from prospector.store.mail import MailRepo
from prospector.store.scores import ScoreRepo

if TYPE_CHECKING:
    from prospector.llm.client import LLMClient
    from prospector.rank.embed import Embedder
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
    verifier: "AccessVerifier | None" = None
    embedder: "Embedder | None" = None
    llm: "LLMClient | None" = None
    sources: "list[Source]" = field(default_factory=list)

    @classmethod
    def create(cls, settings: Settings, conn: sqlite3.Connection, profile: Profile, http: httpx.Client,
               **extra) -> "AppContext":
        return cls(settings=settings, conn=conn, profile=profile, http=http,
                   leads=LeadRepo(conn), scores=ScoreRepo(conn), feedback=FeedbackRepo(conn),
                   health=HealthRepo(conn), mail=MailRepo(conn), kv=KV(conn), **extra)
