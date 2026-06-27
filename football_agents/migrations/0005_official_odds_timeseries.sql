CREATE TABLE IF NOT EXISTS official_odds_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    official_match_id TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    sale_status TEXT NOT NULL,
    home_sp REAL NOT NULL CHECK(home_sp > 1),
    draw_sp REAL NOT NULL CHECK(draw_sp > 1),
    away_sp REAL NOT NULL CHECK(away_sp > 1),
    is_pre_match INTEGER NOT NULL CHECK(is_pre_match IN (0,1)),
    minutes_to_kickoff REAL NOT NULL,
    capture_stage TEXT NOT NULL,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    raw_hash TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(match_id, observed_at)
);
CREATE INDEX IF NOT EXISTS idx_official_observations_match_time
ON official_odds_observations(match_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_official_observations_stage_time
ON official_odds_observations(capture_stage, observed_at);

CREATE TRIGGER IF NOT EXISTS official_odds_observations_no_update
BEFORE UPDATE ON official_odds_observations
BEGIN
    SELECT RAISE(ABORT, 'official odds observations are immutable');
END;

CREATE TRIGGER IF NOT EXISTS official_odds_observations_no_delete
BEFORE DELETE ON official_odds_observations
BEGIN
    SELECT RAISE(ABORT, 'official odds observations are immutable');
END;

CREATE VIEW IF NOT EXISTS official_odds_closing_observations AS
SELECT observation.*
FROM official_odds_observations observation
WHERE observation.is_pre_match=1
  AND observation.observed_at=(
      SELECT MAX(candidate.observed_at)
      FROM official_odds_observations candidate
      WHERE candidate.match_id=observation.match_id
        AND candidate.is_pre_match=1
        AND unixepoch(candidate.observed_at)<=unixepoch(candidate.kickoff_time)
  );
