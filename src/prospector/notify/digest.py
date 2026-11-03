import html
from dataclasses import dataclass
from datetime import datetime, timedelta

from prospector.store.health import HealthRepo
from prospector.store.kv import KV
from prospector.store.leads import LeadRepo, LeadRow

TELEGRAM_LIMIT = 4096
_TITLE_MAX = 300


@dataclass
class Digest:
    items: list[LeadRow]
    deadlines: list[LeadRow]
    warnings: list[str]
    dashboard_url: str


def build_digest(leads: LeadRepo, health: HealthRepo, kv: KV, now: datetime, dashboard_url: str) -> Digest:
    last = kv.get("last_digest_at")
    since = datetime.fromisoformat(last) if last else now - timedelta(hours=24)
    warnings = []
    for h in health.all():
        if h.paused:
            warnings.append(f"{h.source_id} paused: {h.last_error}")
        elif h.drift:
            warnings.append(f"{h.source_id} returned suspicious results")
    return Digest(
        items=leads.new_since(since, limit=10),
        deadlines=leads.starred_with_deadline_within(3, now.date()),
        warnings=warnings,
        dashboard_url=dashboard_url.rstrip("/"),
    )


def _line(row: LeadRow, base: str, escape) -> tuple[str, str, str]:
    l = row.lead
    score = f"{row.stage1:.2f}" if row.stage1 is not None else "–"
    title = escape(l.title[:_TITLE_MAX])
    meta = f"{escape(l.company or '?')} · {l.kind.value}"
    if row.stage2:
        meta += f" · ★ {escape(row.stage2.get('verdict', ''))}"
    return score, f"{title} — {meta}", f"{base}/lead/{l.id}"


def render_telegram(d: Digest) -> list[str]:
    blocks = [f"<b>Prospector</b> — {len(d.items)} new leads"]
    for row in d.items:
        score, text, url = _line(row, d.dashboard_url, html.escape)
        blocks.append(f"<b>{score}</b> {text}\n{url}")
    if d.deadlines:
        blocks.append("<b>Deadlines within 3 days</b>")
        for row in d.deadlines:
            _, text, url = _line(row, d.dashboard_url, html.escape)
            blocks.append(f"⏰ {row.lead.deadline} {text}\n{url}")
    blocks += [f"⚠ {html.escape(w)}" for w in d.warnings]
    blocks.append(d.dashboard_url)

    chunks, current = [], ""
    for block in blocks:
        block = block[:TELEGRAM_LIMIT]
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > TELEGRAM_LIMIT:
            chunks.append(current)
            current = block
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def render_email(d: Digest) -> tuple[str, str, str]:
    subject = f"Prospector: {len(d.items)} new leads"
    text_lines, html_lines = [], [f"<h2>{html.escape(subject)}</h2><ol>"]
    for row in d.items:
        score, text, url = _line(row, d.dashboard_url, lambda s: s)
        _, etext, _ = _line(row, d.dashboard_url, html.escape)
        text_lines.append(f"{score}  {text}\n      {url}")
        html_lines.append(f'<li><b>{score}</b> <a href="{url}">{etext}</a></li>')
    html_lines.append("</ol>")
    if d.deadlines:
        text_lines.append("\nDeadlines within 3 days:")
        html_lines.append("<h3>Deadlines within 3 days</h3><ul>")
        for row in d.deadlines:
            _, text, url = _line(row, d.dashboard_url, lambda s: s)
            _, etext, _ = _line(row, d.dashboard_url, html.escape)
            text_lines.append(f"  {row.lead.deadline}  {text}  {url}")
            html_lines.append(f'<li>{row.lead.deadline} <a href="{url}">{etext}</a></li>')
        html_lines.append("</ul>")
    for w in d.warnings:
        text_lines.append(f"⚠ {w}")
        html_lines.append(f"<p>⚠ {html.escape(w)}</p>")
    text_lines.append(f"\n{d.dashboard_url}")
    html_lines.append(f'<p><a href="{d.dashboard_url}">Open dashboard</a></p>')
    return subject, "\n".join(text_lines), "\n".join(html_lines)
