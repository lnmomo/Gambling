CREATE TABLE IF NOT EXISTS external_consensus_policy_registrations (
    policy_id TEXT PRIMARY KEY,
    policy_hash TEXT NOT NULL UNIQUE,
    policy_name TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    config_json TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS external_consensus_decisions (
    decision_id TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL REFERENCES external_consensus_policy_registrations(policy_id),
    study_id TEXT NOT NULL REFERENCES prospective_research_studies(study_id),
    freeze_id TEXT NOT NULL REFERENCES prospective_model_freezes(freeze_id),
    match_id INTEGER NOT NULL REFERENCES matches(id),
    official_match_id TEXT NOT NULL,
    official_odds_observation_id INTEGER NOT NULL REFERENCES official_odds_observations(id),
    external_fetched_at TEXT NOT NULL,
    source_prediction_id TEXT NOT NULL REFERENCES prospective_predictions(prediction_id),
    decided_at TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    minutes_to_kickoff REAL NOT NULL,
    bookmaker_count INTEGER NOT NULL,
    external_home_probability REAL NOT NULL,
    external_draw_probability REAL NOT NULL,
    external_away_probability REAL NOT NULL,
    external_home_std REAL NOT NULL,
    external_draw_std REAL NOT NULL,
    external_away_std REAL NOT NULL,
    selected_outcome TEXT,
    selected_sp REAL,
    selected_probability REAL,
    conservative_probability REAL,
    expected_ev REAL,
    conservative_ev REAL,
    action TEXT NOT NULL CHECK(action IN ('CANDIDATE','NO_BET')),
    blockers_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(policy_id, official_odds_observation_id, external_fetched_at)
);

CREATE INDEX IF NOT EXISTS idx_external_consensus_decisions_policy_time
ON external_consensus_decisions(policy_id, decided_at);

CREATE INDEX IF NOT EXISTS idx_external_consensus_decisions_match
ON external_consensus_decisions(match_id, kickoff_time);

CREATE TRIGGER IF NOT EXISTS external_consensus_policies_no_update
BEFORE UPDATE ON external_consensus_policy_registrations BEGIN
    SELECT RAISE(ABORT, 'external consensus policies are immutable');
END;

CREATE TRIGGER IF NOT EXISTS external_consensus_policies_no_delete
BEFORE DELETE ON external_consensus_policy_registrations BEGIN
    SELECT RAISE(ABORT, 'external consensus policies are immutable');
END;

CREATE TRIGGER IF NOT EXISTS external_consensus_decisions_no_update
BEFORE UPDATE ON external_consensus_decisions BEGIN
    SELECT RAISE(ABORT, 'external consensus decisions are immutable');
END;

CREATE TRIGGER IF NOT EXISTS external_consensus_decisions_no_delete
BEFORE DELETE ON external_consensus_decisions BEGIN
    SELECT RAISE(ABORT, 'external consensus decisions are immutable');
END;
