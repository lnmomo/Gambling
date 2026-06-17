CREATE TABLE IF NOT EXISTS true_odds_config_versions (
    config_version_id TEXT PRIMARY KEY,
    config_name TEXT NOT NULL,
    config_json TEXT NOT NULL,
    source_optimization_run_id TEXT,
    source_optimization_summary_json TEXT,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL,
    status TEXT NOT NULL,
    shadow_started_at TEXT,
    shadow_ended_at TEXT,
    activated_at TEXT,
    promotion_status TEXT NOT NULL,
    warnings_json TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_true_odds_config_versions_status ON true_odds_config_versions(status);
CREATE INDEX IF NOT EXISTS idx_true_odds_config_versions_promotion_status ON true_odds_config_versions(promotion_status);
CREATE INDEX IF NOT EXISTS idx_true_odds_config_versions_created_at ON true_odds_config_versions(created_at);
CREATE INDEX IF NOT EXISTS idx_true_odds_config_versions_source_run ON true_odds_config_versions(source_optimization_run_id);

CREATE TABLE IF NOT EXISTS live_shadow_predictions (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    match_id TEXT NOT NULL,
    official_match_id TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    league TEXT,
    config_version_id TEXT NOT NULL,
    true_odds_config_snapshot_json TEXT NOT NULL,
    official_sp_snapshot_id TEXT,
    external_odds_snapshot_id TEXT,
    baseline_prediction_id TEXT,
    baseline_recommendation TEXT NOT NULL,
    baseline_selected_outcome TEXT,
    baseline_ev REAL,
    baseline_probability REAL,
    baseline_official_sp REAL,
    shadow_recommendation TEXT NOT NULL,
    shadow_selected_outcome TEXT,
    shadow_ev REAL,
    shadow_lower_bound_ev REAL,
    shadow_edge_quality_score REAL,
    shadow_edge_quality_level TEXT,
    shadow_adaptive_threshold REAL,
    shadow_passes_true_odds_filter INTEGER NOT NULL,
    shadow_would_block_baseline INTEGER NOT NULL,
    shadow_would_recommend_new INTEGER NOT NULL,
    no_bet_reason TEXT,
    true_odds_estimate_json TEXT,
    lifecycle_status TEXT NOT NULL,
    warnings_json TEXT,
    UNIQUE(official_match_id, config_version_id, official_sp_snapshot_id, external_odds_snapshot_id)
);
CREATE INDEX IF NOT EXISTS idx_live_shadow_predictions_official_match ON live_shadow_predictions(official_match_id);
CREATE INDEX IF NOT EXISTS idx_live_shadow_predictions_config ON live_shadow_predictions(config_version_id);
CREATE INDEX IF NOT EXISTS idx_live_shadow_predictions_created_at ON live_shadow_predictions(created_at);
CREATE INDEX IF NOT EXISTS idx_live_shadow_predictions_kickoff ON live_shadow_predictions(kickoff_time);
CREATE INDEX IF NOT EXISTS idx_live_shadow_predictions_lifecycle ON live_shadow_predictions(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_live_shadow_predictions_edge_level ON live_shadow_predictions(shadow_edge_quality_level);
CREATE INDEX IF NOT EXISTS idx_live_shadow_predictions_blocked ON live_shadow_predictions(shadow_would_block_baseline);

CREATE TABLE IF NOT EXISTS shadow_post_match_results (
    id TEXT PRIMARY KEY,
    shadow_prediction_id TEXT NOT NULL UNIQUE,
    match_id TEXT NOT NULL,
    official_match_id TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    actual_result TEXT,
    closing_sp_json TEXT,
    closing_probability_json TEXT,
    baseline_profit REAL,
    shadow_profit REAL,
    baseline_clv REAL,
    shadow_clv REAL,
    baseline_hit INTEGER,
    shadow_hit INTEGER,
    baseline_would_have_bet INTEGER NOT NULL,
    shadow_would_have_bet INTEGER NOT NULL,
    shadow_blocked_baseline INTEGER NOT NULL,
    shadow_added_new_recommendation INTEGER NOT NULL,
    evaluation_status TEXT NOT NULL,
    warnings_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_shadow_post_match_results_official_match ON shadow_post_match_results(official_match_id);
CREATE INDEX IF NOT EXISTS idx_shadow_post_match_results_evaluated_at ON shadow_post_match_results(evaluated_at);
CREATE INDEX IF NOT EXISTS idx_shadow_post_match_results_status ON shadow_post_match_results(evaluation_status);
CREATE INDEX IF NOT EXISTS idx_shadow_post_match_results_blocked ON shadow_post_match_results(shadow_blocked_baseline);

CREATE TABLE IF NOT EXISTS shadow_validation_runs (
    id TEXT PRIMARY KEY,
    config_version_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    from_date TEXT,
    to_date TEXT,
    metrics_json TEXT NOT NULL,
    promotion_gate_result_json TEXT NOT NULL,
    decision TEXT NOT NULL,
    recommended_for_production INTEGER NOT NULL,
    warnings_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_shadow_validation_runs_config ON shadow_validation_runs(config_version_id);
CREATE INDEX IF NOT EXISTS idx_shadow_validation_runs_created_at ON shadow_validation_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_shadow_validation_runs_decision ON shadow_validation_runs(decision);
