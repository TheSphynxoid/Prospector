import logging
from collections.abc import Callable

from prospector.config import Settings
from prospector.sources.base import Source
from prospector.store.mail import MailRepo

log = logging.getLogger(__name__)

# id -> factory(settings, mail) returning a Source, or None when credentials are missing.
FACTORIES: dict[str, Callable[[Settings, MailRepo], Source | None]] = {}


def register(source_id: str):
    def deco(factory):
        FACTORIES[source_id] = factory
        return factory
    return deco


def known_source_ids() -> list[str]:
    import prospector.sources.adapters  # noqa: F401 — registers every adapter
    return list(FACTORIES)


def build_sources(settings: Settings, mail: MailRepo) -> list[Source]:
    import prospector.sources.adapters  # noqa: F401 — registers every adapter

    out = []
    for sid in settings.enabled_sources:
        factory = FACTORIES.get(sid)
        if factory is None:
            log.warning("unknown source %s", sid)
            continue
        source = factory(settings, mail)
        if source is None:
            log.warning("source %s skipped: missing credentials", sid)
            continue
        out.append(source)
    return out
