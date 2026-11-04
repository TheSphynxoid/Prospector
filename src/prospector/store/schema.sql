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

CREATE TABLE IF NOT EXISTS lead_messages (
    id INTEGER PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lead_messages_lead ON lead_messages(lead_id, id);

CREATE TABLE IF NOT EXISTS lead_assist (
    lead_id INTEGER PRIMARY KEY REFERENCES leads(id) ON DELETE CASCADE,
    posting TEXT,
    posting_origin TEXT,
    fetch_note TEXT,
    fetch_tried INTEGER NOT NULL DEFAULT 0,
    bid TEXT
);

-- Lead expiry: why a lead looks closed (expired, or a badge on starred/applied), and reasons the owner overrode.
CREATE TABLE IF NOT EXISTS lead_flags (
    lead_id INTEGER PRIMARY KEY REFERENCES leads(id) ON DELETE CASCADE,
    closed_key TEXT,
    closed_reason TEXT,
    closed_at TEXT,
    ignored TEXT NOT NULL DEFAULT '[]'
);

-- Source-side ids (e.g. the Freelancer project id) for closed checks.
CREATE TABLE IF NOT EXISTS lead_refs (
    lead_id INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    external_id TEXT NOT NULL,
    PRIMARY KEY (lead_id, source_id)
);

CREATE TABLE IF NOT EXISTS fx_rates (
    day TEXT NOT NULL,
    code TEXT NOT NULL,
    per_usd REAL NOT NULL,
    source TEXT NOT NULL,
    PRIMARY KEY (day, code)
);
