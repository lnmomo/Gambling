CREATE TABLE IF NOT EXISTS prospective_external_odds_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    official_match_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    sport_key TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    bookmaker_key TEXT NOT NULL,
    market TEXT NOT NULL CHECK(market='H2H'),
    home_odds REAL NOT NULL CHECK(home_odds>1),
    draw_odds REAL NOT NULL CHECK(draw_odds>1),
    away_odds REAL NOT NULL CHECK(away_odds>1),
    bookmaker_last_update TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    minutes_to_kickoff REAL NOT NULL CHECK(minutes_to_kickoff>0),
    capture_window TEXT NOT NULL CHECK(capture_window IN ('T_MINUS_24H','T_MINUS_6H','T_MINUS_1H','OTHER_PRE_MATCH')),
    source TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    raw_event_json TEXT NOT NULL,
    UNIQUE(match_id,event_id,bookmaker_key,capture_window)
);

CREATE INDEX IF NOT EXISTS idx_prospective_external_odds_match_time
ON prospective_external_odds_snapshots(match_id,captured_at);

CREATE TABLE IF NOT EXISTS odds_api_quota_ledger (
    request_id TEXT PRIMARY KEY,
    requested_at TEXT NOT NULL,
    sport_key TEXT NOT NULL,
    endpoint TEXT NOT NULL,
    regions TEXT NOT NULL,
    markets TEXT NOT NULL,
    estimated_cost INTEGER NOT NULL CHECK(estimated_cost>=0),
    credits_last INTEGER,
    credits_remaining INTEGER,
    credits_used INTEGER,
    events_returned INTEGER NOT NULL DEFAULT 0,
    response_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_odds_api_quota_month
ON odds_api_quota_ledger(requested_at);

CREATE TRIGGER IF NOT EXISTS prospective_external_odds_no_update
BEFORE UPDATE ON prospective_external_odds_snapshots BEGIN
    SELECT RAISE(ABORT, 'prospective external odds snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS prospective_external_odds_no_delete
BEFORE DELETE ON prospective_external_odds_snapshots BEGIN
    SELECT RAISE(ABORT, 'prospective external odds snapshots are immutable');
END;

CREATE TRIGGER IF NOT EXISTS odds_api_quota_ledger_no_update
BEFORE UPDATE ON odds_api_quota_ledger BEGIN
    SELECT RAISE(ABORT, 'odds API quota ledger is immutable');
END;

CREATE TRIGGER IF NOT EXISTS odds_api_quota_ledger_no_delete
BEFORE DELETE ON odds_api_quota_ledger BEGIN
    SELECT RAISE(ABORT, 'odds API quota ledger is immutable');
END;
