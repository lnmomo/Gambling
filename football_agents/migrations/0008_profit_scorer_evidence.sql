CREATE TABLE IF NOT EXISTS profit_scorer_evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id INTEGER NOT NULL REFERENCES matches(id),
    official_odds_observation_id INTEGER NOT NULL REFERENCES official_odds_observations(id),
    scorer_artifact_sha256 TEXT NOT NULL,
    strategy_label TEXT NOT NULL,
    selected_outcome TEXT NOT NULL CHECK(selected_outcome IN ('HOME','DRAW','AWAY')),
    feature_engine TEXT NOT NULL,
    feature_json TEXT NOT NULL,
    market_probability REAL NOT NULL CHECK(market_probability > 0 AND market_probability < 1),
    predicted_probability REAL NOT NULL CHECK(predicted_probability > 0 AND predicted_probability < 1),
    predicted_ev REAL NOT NULL,
    passes_scorer INTEGER NOT NULL CHECK(passes_scorer IN (0,1)),
    scored_at TEXT NOT NULL,
    UNIQUE(official_odds_observation_id, scorer_artifact_sha256)
);

CREATE INDEX IF NOT EXISTS idx_profit_scorer_evidence_match
ON profit_scorer_evidence(match_id, scored_at);

CREATE INDEX IF NOT EXISTS idx_profit_scorer_evidence_strategy
ON profit_scorer_evidence(strategy_label, scored_at);

CREATE TRIGGER IF NOT EXISTS profit_scorer_evidence_no_update
BEFORE UPDATE ON profit_scorer_evidence
BEGIN
    SELECT RAISE(ABORT, 'profit scorer evidence is immutable');
END;

CREATE TRIGGER IF NOT EXISTS profit_scorer_evidence_no_delete
BEFORE DELETE ON profit_scorer_evidence
BEGIN
    SELECT RAISE(ABORT, 'profit scorer evidence is immutable');
END;
