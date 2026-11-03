from typing import Protocol

import httpx

from prospector.models import RawLead


class Source(Protocol):
    id: str
    interval_hours: float

    def fetch(self, http: httpx.Client) -> list[RawLead]: ...
