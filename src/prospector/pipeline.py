import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from prospector.context import AppContext
from prospector.llm.client import LLMClient, LLMError
from prospector.models import Lead, Status, company_norm
from prospector.normalize.dedupe import is_duplicate
from prospector.normalize.normalize import normalize
from prospector.notify.digest import build_digest, render_telegram
from prospector.profile.filters import apply_hard_filters
from prospector.rank.embed import lead_text, profile_vectors
from prospector.rank.stage1 import score_stage1
from prospector.rank.stage2 import run_stage2
from prospector.rank.weights import COMPONENTS, Weights, reweight
from prospector.sources.base import Source
from prospector.sources.runner import run_source, should_run
from prospector.store.db import connect

log = logging.getLogger(__name__)
RAW_RETENTION_DAYS = 30
BACKUPS_KEPT = 14


@dataclass
class IngestStats:
    fetched: int = 0
    new: int = 0
    merged: int = 0
    filtered: int = 0


def _find_existing(ctx: AppContext, lead: Lead) -> Lead | None:
    found = ctx.leads.by_canonical_url(lead.canonical_url)
    if found:
        return found
    return next((c for c in ctx.leads.recent_by_company(company_norm(lead.company)) if is_duplicate(lead, c)), None)


def _score(ctx: AppContext, lead: Lead, now: datetime) -> None:
    if ctx.embedder is None:
        return
    if ctx.profile_vecs is None:
        ctx.profile_vecs = profile_vectors(ctx.profile, ctx.embedder)
    vec = ctx.embedder.embed([lead_text(lead)], "passage")[0]
    ctx.scores.save_embedding(lead.id, vec)
    score, breakdown = score_stage1(
        lead, vec, ctx.profile_vecs,
        ctx.scores.embeddings(ctx.feedback.positive_ids()), ctx.scores.embeddings(ctx.feedback.negative_ids()),
        ctx.profile, Weights.load(ctx.kv), now, sim_range=getattr(ctx.embedder, "sim_range", (0.25, 0.65)),
    )
    ctx.scores.save_stage1(lead.id, score, breakdown)


def ingest(ctx: AppContext, source: Source, now: datetime) -> IngestStats:
    stats = IngestStats()
    for raw in run_source(source, ctx.http, ctx.health, now):
        stats.fetched += 1
        try:
            lead = normalize(raw)
            existing = _find_existing(ctx, lead)
            if existing:
                ctx.leads.add_source(existing.id, raw.source_id)
                stats.merged += 1
                continue
            ctx.leads.insert(lead)
            ctx.leads.put_raw(lead.id, raw.source_id, raw.raw_payload)
            reason = apply_hard_filters(lead, ctx.profile)
            if reason:
                ctx.leads.set_status(lead.id, Status.FILTERED, reason)
                stats.filtered += 1
                continue
            _score(ctx, lead, now)
            stats.new += 1
        except Exception as e:  # noqa: BLE001 — one bad posting must not abort the batch
            log.warning("failed to ingest %s from %s: %s", raw.url, raw.source_id, e)
    log.info("ingest %s: %s", source.id, stats)
    return stats


def stage2(ctx: AppContext, today) -> int:
    if ctx.llm is None:
        return 0
    return run_stage2(ctx.leads, ctx.scores, ctx.kv, ctx.llm, ctx.profile,
                      ctx.settings.llm_daily_cap, ctx.settings.stage2_threshold, today)


def tick(ctx: AppContext, now: datetime) -> None:
    """One scheduler pass: run every due source, then stage 2."""
    for source in ctx.sources:
        if should_run(ctx.health.get(source.id), source, now):
            ingest(ctx, source, now)
    stage2(ctx, now.date())


def digest_preview(ctx: AppContext, now: datetime) -> list[str]:
    return render_telegram(build_digest(ctx.leads, ctx.health, ctx.kv, now, ctx.settings.dashboard_url))


def nightly(ctx: AppContext, now: datetime) -> None:
    rows = []
    for ids, positive in ((ctx.feedback.positive_ids(), True), (ctx.feedback.negative_ids(), False)):
        for lead_id in ids:
            bd = ctx.scores.breakdown(lead_id)
            if bd and all(c in bd for c in COMPONENTS):
                rows.append((bd, positive))
    reweight(Weights.load(ctx.kv), rows).save(ctx.kv)
    ctx.leads.prune_raw(RAW_RETENTION_DAYS)

    backups = Path(ctx.settings.data_dir) / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    dest = connect(backups / f"prospector-{now:%Y%m%d}.db")
    try:
        ctx.conn.backup(dest)
    finally:
        dest.close()
    for old in sorted(backups.glob("prospector-*.db"))[:-BACKUPS_KEPT]:
        old.unlink()


def select_model(client: LLMClient, primary: str, fallback: str) -> str | None:
    try:
        available = set(client.list_models())
    except LLMError as e:
        log.warning("could not list LLM models (%s); keeping %s", e, primary)
        return primary
    if primary in available:
        return primary
    if fallback in available:
        log.warning("LLM model %s unavailable; using %s", primary, fallback)
        return fallback
    log.error("neither %s nor %s is available; stage 2 disabled", primary, fallback)
    return None
