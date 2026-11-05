from typing import Protocol

import httpx

from prospector.models import RawLead


class Source(Protocol):
    id: str
    interval_hours: float
    # Optional: `may_be_empty = True` when no leads is normal (seasonal programs); otherwise 0 leads flags drift.

    def fetch(self, http: httpx.Client) -> list[RawLead]: ...
