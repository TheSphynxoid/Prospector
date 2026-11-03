"""Core domain types shared by every module."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Literal


def utcnow() -> datetime:
    return datetime.now(UTC)


class Kind(StrEnum):
    JOB = "job"
    CONTRACT = "contract"
    GIG = "gig"
    BOUNTY = "bounty"
    PFE = "pfe"
    AI_TRAINING = "ai_training"


class Remote(StrEnum):
    YES = "yes"
    NO = "no"
    HYBRID = "hybrid"
    UNKNOWN = "unknown"


class Status(StrEnum):
    NEW = "new"
    STARRED = "starred"
    DISMISSED = "dismissed"
    APPLIED = "applied"
    FILTERED = "filtered"


PayPeriod = Literal["hour", "day", "month", "year", "fixed"]


@dataclass(frozen=True)
class Pay:
    min: float | None
    max: float | None
    currency: str | None
    period: PayPeriod | None


@dataclass
class RawLead:
    source_id: str
    external_id: str
    url: str
    title: str
    body: str
    company: str | None = None
    location_text: str | None = None
    pay_text: str | None = None
    posted_at: datetime | None = None
    deadline: date | None = None
    kind_hint: Kind | None = None
    raw_payload: str = ""
    fetched_at: datetime = field(default_factory=utcnow)


@dataclass
class Lead:
    canonical_url: str
    title: str
    company: str | None
    kind: Kind
    remote: Remote
    remote_region: str | None
    locations: list[str]
    pay: Pay | None
    languages: list[str]
    deadline: date | None
    posted_at: datetime | None
    body: str
    content_hash: str
    sources: list[str]
    status: Status = Status.NEW
    filter_reason: str | None = None
    id: int | None = None


_LEGAL_SUFFIXES = {"inc", "ltd", "llc", "sarl", "sas", "gmbh", "sa", "corp", "co"}


def company_norm(name: str | None) -> str:
    """Lowercased company name without punctuation or legal suffixes."""
    if not name:
        return ""
    words = re.sub(r"[^\w\s]", " ", name.lower()).split()
    return " ".join(w for w in words if w not in _LEGAL_SUFFIXES)
