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

