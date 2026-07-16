CREATE TABLE IF NOT EXISTS official_market_availability_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    official_match_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    raw_sale_status TEXT NOT NULL,
    normalized_status TEXT NOT NULL,
    has_valid_three_way_sp INTEGER NOT NULL CHECK(has_valid_three_way_sp IN (0,1)),
    missing_reason TEXT,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    raw_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(match_id, observed_at)
);

CREATE INDEX IF NOT EXISTS idx_official_market_availability_time
ON official_market_availability_observations(observed_at, kickoff_time);

CREATE INDEX IF NOT EXISTS idx_official_market_availability_sale_status
ON official_market_availability_observations(raw_sale_status, has_valid_three_way_sp, observed_at);

CREATE TRIGGER IF NOT EXISTS official_market_availability_no_update
BEFORE UPDATE ON official_market_availability_observations
BEGIN
    SELECT RAISE(ABORT, 'official market availability observations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS official_market_availability_no_delete
BEFORE DELETE ON official_market_availability_observations
BEGIN
    SELECT RAISE(ABORT, 'official market availability observations are immutable');
END;
