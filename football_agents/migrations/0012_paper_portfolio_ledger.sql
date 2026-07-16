CREATE TABLE IF NOT EXISTS paper_portfolio_runs (
    run_id TEXT PRIMARY KEY,
    run_hash TEXT NOT NULL UNIQUE,
    decision_at TEXT NOT NULL,
    allocation_date TEXT NOT NULL,
    daily_budget REAL NOT NULL CHECK(daily_budget >= 0),
    readiness_decision TEXT NOT NULL,
    readiness_hash TEXT NOT NULL,
    allocated_budget REAL NOT NULL CHECK(allocated_budget >= 0),
    cash_reserved REAL NOT NULL CHECK(cash_reserved >= 0),
    status TEXT NOT NULL CHECK(status IN ('HOLD','ALLOCATED','NO_ELIGIBLE_POSITIONS')),
    details_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS paper_portfolio_positions (
    position_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES paper_portfolio_runs(run_id),
    allocation_date TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    scorer_evidence_id INTEGER NOT NULL REFERENCES profit_scorer_evidence(id),
    match_id INTEGER NOT NULL REFERENCES matches(id),
    official_match_id TEXT NOT NULL,
    official_odds_observation_id INTEGER NOT NULL REFERENCES official_odds_observations(id),
    selected_outcome TEXT NOT NULL CHECK(selected_outcome IN ('HOME','DRAW','AWAY')),
    selected_sp REAL NOT NULL CHECK(selected_sp > 1),
    predicted_probability REAL NOT NULL CHECK(predicted_probability > 0 AND predicted_probability < 1),
    predicted_ev REAL NOT NULL,
    quarter_kelly_fraction REAL NOT NULL CHECK(quarter_kelly_fraction >= 0),
    stake REAL NOT NULL CHECK(stake > 0),
    placed_at TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    scorer_artifact_sha256 TEXT NOT NULL,
    source_payload_hash TEXT NOT NULL,
    UNIQUE(strategy_id, scorer_evidence_id)
);

CREATE TABLE IF NOT EXISTS paper_portfolio_settlements (
    settlement_id TEXT PRIMARY KEY,
    position_id TEXT NOT NULL UNIQUE REFERENCES paper_portfolio_positions(position_id),
    result_id INTEGER NOT NULL REFERENCES results(id),
    closing_odds_observation_id INTEGER REFERENCES official_odds_observations(id),
    actual_outcome TEXT NOT NULL CHECK(actual_outcome IN ('HOME','DRAW','AWAY')),
    closing_sp REAL,
    clv REAL,
    profit REAL NOT NULL,
    settled_at TEXT NOT NULL,
    source_payload_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_paper_portfolio_runs_date
    ON paper_portfolio_runs(allocation_date, decision_at);
CREATE INDEX IF NOT EXISTS idx_paper_positions_date
    ON paper_portfolio_positions(allocation_date, placed_at);
CREATE INDEX IF NOT EXISTS idx_paper_positions_match
    ON paper_portfolio_positions(match_id, placed_at);
CREATE INDEX IF NOT EXISTS idx_paper_settlements_time
    ON paper_portfolio_settlements(settled_at);

CREATE TRIGGER IF NOT EXISTS paper_portfolio_runs_no_update
BEFORE UPDATE ON paper_portfolio_runs BEGIN
    SELECT RAISE(ABORT, 'paper portfolio runs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS paper_portfolio_runs_no_delete
BEFORE DELETE ON paper_portfolio_runs BEGIN
    SELECT RAISE(ABORT, 'paper portfolio runs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS paper_portfolio_positions_no_update
BEFORE UPDATE ON paper_portfolio_positions BEGIN
    SELECT RAISE(ABORT, 'paper portfolio positions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS paper_portfolio_positions_no_delete
BEFORE DELETE ON paper_portfolio_positions BEGIN
    SELECT RAISE(ABORT, 'paper portfolio positions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS paper_portfolio_settlements_no_update
BEFORE UPDATE ON paper_portfolio_settlements BEGIN
    SELECT RAISE(ABORT, 'paper portfolio settlements are immutable');
END;
CREATE TRIGGER IF NOT EXISTS paper_portfolio_settlements_no_delete
BEFORE DELETE ON paper_portfolio_settlements BEGIN
    SELECT RAISE(ABORT, 'paper portfolio settlements are immutable');
END;
