CREATE TABLE IF NOT EXISTS profit_scorer_freeze_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    official_odds_observation_id INTEGER NOT NULL REFERENCES official_odds_observations(id),
    scorer_artifact_sha256 TEXT NOT NULL,
    strategy_label TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('SCORED','BLOCKED','MISSED_PRE_MATCH')),
    blocker_json TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    UNIQUE(official_odds_observation_id, scorer_artifact_sha256)
);

CREATE INDEX IF NOT EXISTS idx_profit_scorer_freeze_strategy
ON profit_scorer_freeze_attempts(strategy_label, attempted_at);

CREATE INDEX IF NOT EXISTS idx_profit_scorer_freeze_match
ON profit_scorer_freeze_attempts(match_id, attempted_at);

CREATE TRIGGER IF NOT EXISTS profit_scorer_freeze_attempts_no_update
BEFORE UPDATE ON profit_scorer_freeze_attempts
BEGIN
    SELECT RAISE(ABORT, 'profit scorer freeze attempts are immutable');
END;

CREATE TRIGGER IF NOT EXISTS profit_scorer_freeze_attempts_no_delete
BEFORE DELETE ON profit_scorer_freeze_attempts
BEGIN
    SELECT RAISE(ABORT, 'profit scorer freeze attempts are immutable');
END;
