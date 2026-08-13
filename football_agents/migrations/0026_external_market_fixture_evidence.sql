ALTER TABLE matches ADD COLUMN source_kind TEXT NOT NULL DEFAULT 'official';

UPDATE matches
SET source_kind='external_market'
WHERE official_match_id LIKE 'oddsapi-%';

CREATE TABLE IF NOT EXISTS external_market_result_observations (
    observation_id TEXT PRIMARY KEY,
    match_id INTEGER REFERENCES matches(id),
    event_id TEXT NOT NULL,
    sport_key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    completed INTEGER NOT NULL CHECK(completed IN (0,1)),
    home_score INTEGER,
    away_score INTEGER,
    resolution_status TEXT NOT NULL,
    resolution_reason TEXT NOT NULL,
    response_hash TEXT NOT NULL UNIQUE,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_external_market_result_event_time
ON external_market_result_observations(event_id, observed_at);

CREATE TRIGGER IF NOT EXISTS external_market_result_observations_no_update
BEFORE UPDATE ON external_market_result_observations BEGIN
    SELECT RAISE(ABORT, 'external market result observations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS external_market_result_observations_no_delete
BEFORE DELETE ON external_market_result_observations BEGIN
    SELECT RAISE(ABORT, 'external market result observations are immutable');
END;
