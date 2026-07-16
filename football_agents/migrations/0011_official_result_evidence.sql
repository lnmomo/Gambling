CREATE TABLE IF NOT EXISTS official_result_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER REFERENCES matches(id),
    official_match_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    match_date TEXT,
    match_no TEXT,
    league TEXT,
    home_team TEXT,
    away_team TEXT,
    home_score INTEGER,
    away_score INTEGER,
    source_result_status TEXT,
    resolution_status TEXT NOT NULL CHECK(resolution_status IN (
        'SETTLED','CONFIRMED','CONFLICT','UNMATCHED','AMBIGUOUS','SKIPPED'
    )),
    resolution_reason TEXT,
    source_url TEXT NOT NULL,
    raw_hash TEXT NOT NULL UNIQUE,
    raw_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_official_result_observations_match
    ON official_result_observations(match_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_official_result_observations_official_match
    ON official_result_observations(official_match_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_official_result_observations_resolution
    ON official_result_observations(resolution_status, observed_at DESC);

CREATE TRIGGER IF NOT EXISTS official_result_observations_no_update
BEFORE UPDATE ON official_result_observations
BEGIN
    SELECT RAISE(ABORT, 'official result observations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS official_result_observations_no_delete
BEFORE DELETE ON official_result_observations
BEGIN
    SELECT RAISE(ABORT, 'official result observations are immutable');
END;
