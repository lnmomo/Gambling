PRAGMA foreign_keys=OFF;

DROP TRIGGER IF EXISTS paper_portfolio_positions_no_update;
DROP TRIGGER IF EXISTS paper_portfolio_positions_no_delete;
DROP INDEX IF EXISTS uq_paper_portfolio_one_match;
DROP INDEX IF EXISTS idx_paper_positions_date;
DROP INDEX IF EXISTS idx_paper_positions_match;

CREATE TABLE paper_portfolio_positions_v2 (
    position_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES paper_portfolio_runs(run_id),
    allocation_date TEXT NOT NULL,
    strategy_id TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK(source_type IN ('PROFIT_SCORER','EXTERNAL_CONSENSUS')),
    scorer_evidence_id INTEGER REFERENCES profit_scorer_evidence(id),
    external_consensus_decision_id TEXT REFERENCES external_consensus_decisions(decision_id),
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
    CHECK(
        (source_type='PROFIT_SCORER' AND scorer_evidence_id IS NOT NULL AND external_consensus_decision_id IS NULL)
        OR
        (source_type='EXTERNAL_CONSENSUS' AND scorer_evidence_id IS NULL AND external_consensus_decision_id IS NOT NULL)
    ),
    UNIQUE(strategy_id, scorer_evidence_id),
    UNIQUE(strategy_id, external_consensus_decision_id)
);

INSERT INTO paper_portfolio_positions_v2(
    position_id,run_id,allocation_date,strategy_id,source_type,scorer_evidence_id,
    external_consensus_decision_id,match_id,official_match_id,official_odds_observation_id,
    selected_outcome,selected_sp,predicted_probability,predicted_ev,quarter_kelly_fraction,
    stake,placed_at,kickoff_time,scorer_artifact_sha256,source_payload_hash
)
SELECT position_id,run_id,allocation_date,strategy_id,'PROFIT_SCORER',scorer_evidence_id,
    NULL,match_id,official_match_id,official_odds_observation_id,selected_outcome,selected_sp,
    predicted_probability,predicted_ev,quarter_kelly_fraction,stake,placed_at,kickoff_time,
    scorer_artifact_sha256,source_payload_hash
FROM paper_portfolio_positions;

DROP TABLE paper_portfolio_positions;
ALTER TABLE paper_portfolio_positions_v2 RENAME TO paper_portfolio_positions;

CREATE INDEX idx_paper_positions_date
ON paper_portfolio_positions(allocation_date, placed_at);
CREATE INDEX idx_paper_positions_match
ON paper_portfolio_positions(match_id, placed_at);
CREATE UNIQUE INDEX uq_paper_portfolio_one_match
ON paper_portfolio_positions(match_id);

CREATE TRIGGER paper_portfolio_positions_no_update
BEFORE UPDATE ON paper_portfolio_positions BEGIN
    SELECT RAISE(ABORT, 'paper portfolio positions are immutable');
END;
CREATE TRIGGER paper_portfolio_positions_no_delete
BEFORE DELETE ON paper_portfolio_positions BEGIN
    SELECT RAISE(ABORT, 'paper portfolio positions are immutable');
END;

PRAGMA foreign_keys=ON;
