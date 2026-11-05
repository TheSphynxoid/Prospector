"""Company career boards: the tech roles of every watched company on Greenhouse, Lever or Ashby.

Each run reads the companies not checked in the last 24 h, up to BATCH, one official API request each. A
failing company is recorded on its own row (3 in a row pause it) and never stops the others.
"""
import logging
from datetime import UTC, datetime

import httpx

from prospector.companies.fetch import BoardError, fetch_board
from prospector.http import describe_error
from prospector.models import RawLead
from prospector.store.companies import CompanyRepo

log = logging.getLogger(__name__)


class CompanyBoards:
    id = "company_boards"
    interval_hours = 1
    may_be_empty = True  # a batch can hold no tech roles, or no company may be due
    BATCH = 40

    def __init__(self, companies: CompanyRepo):
        self.companies = companies

    def fetch(self, http: httpx.Client) -> list[RawLead]:
        batch = self.companies.due(datetime.now(UTC), self.BATCH)
        out: list[RawLead] = []
        last_error: Exception | None = None
        failed = 0
        for company in batch:
            try:
                name, leads = fetch_board(http, company)
            except Exception as e:  # noqa: BLE001 — a bad answer from one board must never stop the others
                last_error, failed = e, failed + 1
                self.companies.record_error(company.id, str(e) if isinstance(e, BoardError) else describe_error(e))
                log.info("company board %s:%s failed: %s", company.board, company.token, e)
                continue
            self.companies.record_ok(company.id, len(leads), name)
            out.extend(leads)
        if batch and failed == len(batch) and last_error is not None:
            raise last_error  # every company failed: report the outage in source health
        return out
