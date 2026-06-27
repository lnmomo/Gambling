CREATE TABLE IF NOT EXISTS prospective_model_freezes (
    freeze_id TEXT PRIMARY KEY,
    algorithm_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    algorithm_hash TEXT NOT NULL UNIQUE,
    config_json TEXT NOT NULL,
    artifact_manifest_json TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS prospective_research_studies (
    study_id TEXT PRIMARY KEY,
    study_name TEXT NOT NULL,
    hypothesis TEXT NOT NULL,
    freeze_id TEXT NOT NULL REFERENCES prospective_model_freezes(freeze_id),
    starts_at TEXT NOT NULL,
    min_settled_matches INTEGER NOT NULL CHECK(min_settled_matches > 0),
    min_calendar_days INTEGER NOT NULL CHECK(min_calendar_days >= 0),
    registered_at TEXT NOT NULL,
    UNIQUE(study_name, freeze_id)
);

CREATE TABLE IF NOT EXISTS prospective_predictions (
    prediction_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL REFERENCES prospective_research_studies(study_id),
    freeze_id TEXT NOT NULL REFERENCES prospective_model_freezes(freeze_id),
    match_id INTEGER NOT NULL REFERENCES matches(id),
    official_match_id TEXT NOT NULL,
    official_odds_observation_id INTEGER NOT NULL REFERENCES official_odds_observations(id),
    source_prediction_id INTEGER NOT NULL REFERENCES model_predictions(id),
    predicted_at TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    model_name TEXT NOT NULL,
    model_version TEXT NOT NULL,
    p_home REAL NOT NULL CHECK(p_home > 0 AND p_home < 1),
    p_draw REAL NOT NULL CHECK(p_draw > 0 AND p_draw < 1),
    p_away REAL NOT NULL CHECK(p_away > 0 AND p_away < 1),
    market_p_home REAL NOT NULL CHECK(market_p_home > 0 AND market_p_home < 1),
    market_p_draw REAL NOT NULL CHECK(market_p_draw > 0 AND market_p_draw < 1),
    market_p_away REAL NOT NULL CHECK(market_p_away > 0 AND market_p_away < 1),
    payload_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    UNIQUE(study_id, official_match_id, official_odds_observation_id)
);
CREATE INDEX IF NOT EXISTS idx_prospective_predictions_study_time
ON prospective_predictions(study_id, predicted_at);
CREATE INDEX IF NOT EXISTS idx_prospective_predictions_match
ON prospective_predictions(match_id);

CREATE TABLE IF NOT EXISTS prospective_confirmation_runs (
    run_id TEXT PRIMARY KEY,
    study_id TEXT NOT NULL UNIQUE REFERENCES prospective_research_studies(study_id),
    freeze_id TEXT NOT NULL REFERENCES prospective_model_freezes(freeze_id),
    executed_at TEXT NOT NULL,
    settled_matches INTEGER NOT NULL,
    elapsed_days INTEGER NOT NULL,
    primary_metric TEXT NOT NULL,
    result_json TEXT NOT NULL,
    decision TEXT NOT NULL
);

CREATE TRIGGER IF NOT EXISTS prospective_model_freezes_no_update
BEFORE UPDATE ON prospective_model_freezes BEGIN
    SELECT RAISE(ABORT, 'prospective model freezes are immutable');
END;
CREATE TRIGGER IF NOT EXISTS prospective_model_freezes_no_delete
BEFORE DELETE ON prospective_model_freezes BEGIN
    SELECT RAISE(ABORT, 'prospective model freezes are immutable');
END;
CREATE TRIGGER IF NOT EXISTS prospective_studies_no_update
BEFORE UPDATE ON prospective_research_studies BEGIN
    SELECT RAISE(ABORT, 'prospective studies are immutable');
END;
CREATE TRIGGER IF NOT EXISTS prospective_studies_no_delete
BEFORE DELETE ON prospective_research_studies BEGIN
    SELECT RAISE(ABORT, 'prospective studies are immutable');
END;
CREATE TRIGGER IF NOT EXISTS prospective_predictions_no_update
BEFORE UPDATE ON prospective_predictions BEGIN
    SELECT RAISE(ABORT, 'prospective predictions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS prospective_predictions_no_delete
BEFORE DELETE ON prospective_predictions BEGIN
    SELECT RAISE(ABORT, 'prospective predictions are immutable');
END;
CREATE TRIGGER IF NOT EXISTS prospective_confirmation_runs_no_update
BEFORE UPDATE ON prospective_confirmation_runs BEGIN
    SELECT RAISE(ABORT, 'prospective confirmation runs are immutable');
END;
CREATE TRIGGER IF NOT EXISTS prospective_confirmation_runs_no_delete
BEFORE DELETE ON prospective_confirmation_runs BEGIN
    SELECT RAISE(ABORT, 'prospective confirmation runs are immutable');
END;
