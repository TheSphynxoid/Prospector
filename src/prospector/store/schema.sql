CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY,
    canonical_url TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    company TEXT,
    company_norm TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    remote TEXT NOT NULL,
    remote_region TEXT,
    locations TEXT NOT NULL DEFAULT '[]',
    pay TEXT,
    languages TEXT NOT NULL DEFAULT '[]',
    deadline TEXT,
    posted_at TEXT,
    body TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    sources TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'new',
    filter_reason TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS leads_company ON leads(company_norm, created_at);
CREATE INDEX IF NOT EXISTS leads_status ON leads(status, created_at);

CREATE TABLE IF NOT EXISTS raw_payloads (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    stored_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scores (
    lead_id INTEGER PRIMARY KEY REFERENCES leads(id) ON DELETE CASCADE,
    stage1 REAL,
    breakdown TEXT,
    stage2 TEXT,
    embedding BLOB,
    scored_at TEXT
);

CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_health (
    source_id TEXT PRIMARY KEY,
    last_run TEXT,
    last_ok TEXT,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_count INTEGER,
    last_error TEXT,
    paused INTEGER NOT NULL DEFAULT 0,
    drift INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS mails (
    id INTEGER PRIMARY KEY,
    raw BLOB NOT NULL,
    received_at TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'pending',
    note TEXT,
    url TEXT,
    dismissed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
