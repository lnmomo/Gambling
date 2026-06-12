PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    official_match_id TEXT UNIQUE NOT NULL,
    league TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    source TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT '1x2',
    option TEXT NOT NULL CHECK(option IN ('home','draw','away')),
    sp REAL NOT NULL CHECK(sp > 1),
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_odds_match_time ON odds_snapshots(match_id, fetched_at DESC);

CREATE TABLE IF NOT EXISTS market_odds_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    bookmaker TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT '1x2',
    option TEXT NOT NULL CHECK(option IN ('home','draw','away')),
    odds REAL NOT NULL CHECK(odds > 1),
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS news_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    team TEXT,
    player TEXT,
    event_type TEXT NOT NULL,
    severity REAL NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    source_url TEXT,
    published_at TEXT NOT NULL,
    raw_text TEXT
);

CREATE TABLE IF NOT EXISTS weather_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    temperature REAL,
    humidity REAL,
    rainfall REAL,
    wind_speed REAL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    feature_version TEXT NOT NULL,
    feature_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    p_home REAL NOT NULL,
    p_draw REAL NOT NULL,
    p_away REAL NOT NULL,
    fair_odds_home REAL NOT NULL,
    fair_odds_draw REAL NOT NULL,
    fair_odds_away REAL NOT NULL,
    predicted_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS critic_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    pass_check INTEGER NOT NULL,
    risk_level TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bet_signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    market TEXT NOT NULL,
    option TEXT,
    sp REAL,
    probability REAL,
    fair_odds REAL,
    ev REAL,
    stake REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL CHECK(status IN ('BET','WATCH','NO_BET')),
    confidence TEXT NOT NULL,
    reasons_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER UNIQUE NOT NULL REFERENCES matches(id),
    home_score INTEGER NOT NULL,
    away_score INTEGER NOT NULL,
    outcome TEXT NOT NULL,
    settled_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bankroll_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER REFERENCES bet_signals(id),
    event_type TEXT NOT NULL,
    amount REAL NOT NULL,
    balance_after REAL NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtest_reports (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    parameters_json TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    equity_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS official_fetch_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    status_code INTEGER,
    raw_hash TEXT,
    record_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT
);

CREATE TABLE IF NOT EXISTS match_status_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    old_status TEXT,
    new_status TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS match_metadata (
    match_id INTEGER PRIMARY KEY REFERENCES matches(id),
    venue TEXT,
    city TEXT,
    country TEXT,
    latitude REAL,
    longitude REAL,
    source TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_sync_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    match_id INTEGER REFERENCES matches(id),
    status TEXT NOT NULL,
    records INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    synced_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    setting_key TEXT PRIMARY KEY,
    setting_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    operator TEXT NOT NULL DEFAULT 'system',
    module TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS llm_match_analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    analysis_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(match_id, provider, model, input_hash)
);

