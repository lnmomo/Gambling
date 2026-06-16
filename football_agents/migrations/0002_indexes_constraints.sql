CREATE INDEX IF NOT EXISTS idx_official_matches_official_id ON official_matches(official_match_id);
CREATE INDEX IF NOT EXISTS idx_official_matches_kickoff ON official_matches(kickoff_time);
CREATE INDEX IF NOT EXISTS idx_official_matches_status ON official_matches(status);
CREATE INDEX IF NOT EXISTS idx_official_matches_league ON official_matches(league);

CREATE INDEX IF NOT EXISTS idx_official_sp_official_id ON official_sp_snapshots(official_match_id);
CREATE INDEX IF NOT EXISTS idx_official_sp_captured ON official_sp_snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_official_sp_type ON official_sp_snapshots(snapshot_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_official_sp_snapshot_payload
ON official_sp_snapshots(official_match_id, raw_payload_hash)
WHERE raw_payload_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_official_sp_snapshot_exact
ON official_sp_snapshots(official_match_id, captured_at, raw_payload_hash)
WHERE raw_payload_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_external_odds_official_id ON external_odds_snapshots(official_match_id);
CREATE INDEX IF NOT EXISTS idx_external_odds_captured ON external_odds_snapshots(captured_at);
CREATE INDEX IF NOT EXISTS idx_external_odds_type ON external_odds_snapshots(snapshot_type);
CREATE UNIQUE INDEX IF NOT EXISTS uq_external_odds_snapshot_payload
ON external_odds_snapshots(official_match_id, raw_payload_hash)
WHERE raw_payload_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_external_odds_snapshot_exact
ON external_odds_snapshots(official_match_id, captured_at, raw_payload_hash)
WHERE raw_payload_hash IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_normalized_bookmakers_snapshot ON normalized_bookmakers(external_snapshot_id);
CREATE INDEX IF NOT EXISTS idx_normalized_bookmakers_key ON normalized_bookmakers(bookmaker_key);
CREATE INDEX IF NOT EXISTS idx_normalized_bookmakers_included ON normalized_bookmakers(included);

CREATE INDEX IF NOT EXISTS idx_predictions_official_id ON predictions(official_match_id);
CREATE INDEX IF NOT EXISTS idx_predictions_created ON predictions(created_at);
CREATE INDEX IF NOT EXISTS idx_predictions_recommendation ON predictions(recommendation);
CREATE INDEX IF NOT EXISTS idx_predictions_lifecycle ON predictions(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_predictions_official_created ON predictions(official_match_id, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_prediction_inputs
ON predictions(official_match_id, official_sp_snapshot_id, external_odds_snapshot_id, model_version)
WHERE official_sp_snapshot_id IS NOT NULL OR external_odds_snapshot_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_recommendations_official_id ON recommendations(official_match_id);
CREATE INDEX IF NOT EXISTS idx_recommendations_lifecycle ON recommendations(lifecycle_status);
CREATE INDEX IF NOT EXISTS idx_recommendations_created ON recommendations(created_at);
CREATE INDEX IF NOT EXISTS idx_recommendations_lifecycle_created ON recommendations(lifecycle_status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_active_recommendation_per_match
ON recommendations(official_match_id)
WHERE lifecycle_status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS idx_recommendation_events_official_id ON recommendation_lifecycle_events(official_match_id);
CREATE INDEX IF NOT EXISTS idx_recommendation_events_occurred ON recommendation_lifecycle_events(occurred_at);
CREATE INDEX IF NOT EXISTS idx_recommendation_events_status ON recommendation_lifecycle_events(new_status);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_type ON audit_logs(entity_type);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_id ON audit_logs(entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_severity ON audit_logs(severity);
CREATE INDEX IF NOT EXISTS idx_audit_logs_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_logs_entity_created ON audit_logs(entity_id, created_at);

CREATE INDEX IF NOT EXISTS idx_bankroll_transactions_bankroll ON bankroll_transactions(bankroll_id);
CREATE INDEX IF NOT EXISTS idx_bankroll_transactions_created ON bankroll_transactions(created_at);
CREATE INDEX IF NOT EXISTS idx_bankroll_transactions_official_id ON bankroll_transactions(official_match_id);

CREATE INDEX IF NOT EXISTS idx_model_governance_role ON model_governance_records(role);
CREATE INDEX IF NOT EXISTS idx_model_governance_type ON model_governance_records(model_type);
CREATE INDEX IF NOT EXISTS idx_model_governance_version ON model_governance_records(version);
CREATE INDEX IF NOT EXISTS idx_model_governance_promotion ON model_governance_records(promotion_status);
CREATE UNIQUE INDEX IF NOT EXISTS uq_current_champion_model
ON model_governance_records(role)
WHERE role = 'CHAMPION' AND archived_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_backtest_runs_created ON backtest_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_status ON backtest_runs(status);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_model_version ON backtest_runs(model_version);
CREATE INDEX IF NOT EXISTS idx_backtest_records_run ON backtest_records(backtest_run_id);
CREATE INDEX IF NOT EXISTS idx_backtest_records_official_id ON backtest_records(official_match_id);
CREATE INDEX IF NOT EXISTS idx_backtest_records_kickoff ON backtest_records(kickoff_time);
CREATE INDEX IF NOT EXISTS idx_backtest_records_league ON backtest_records(league);

CREATE INDEX IF NOT EXISTS idx_task_runs_name_started ON task_runs(task_name, started_at);
CREATE INDEX IF NOT EXISTS idx_task_runs_status_started ON task_runs(status, started_at);
