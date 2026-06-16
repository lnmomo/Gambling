PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS official_matches (
    id TEXT PRIMARY KEY,
    official_match_id TEXT UNIQUE NOT NULL,
    league TEXT NOT NULL,
    home_team TEXT NOT NULL,
    away_team TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS official_sp_snapshots (
    id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    official_match_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    snapshot_type TEXT NOT NULL,
    home_sp REAL NOT NULL,
    draw_sp REAL NOT NULL,
    away_sp REAL NOT NULL,
    market_home_prob REAL NOT NULL,
    market_draw_prob REAL NOT NULL,
    market_away_prob REAL NOT NULL,
    market_home_fair_odds REAL NOT NULL,
    market_draw_fair_odds REAL NOT NULL,
    market_away_fair_odds REAL NOT NULL,
    raw_payload_hash TEXT,
    is_valid INTEGER NOT NULL,
    warnings_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS external_odds_snapshots (
    id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    official_match_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    snapshot_type TEXT NOT NULL,
    external_home_prob REAL NOT NULL,
    external_draw_prob REAL NOT NULL,
    external_away_prob REAL NOT NULL,
    external_home_fair_odds REAL NOT NULL,
    external_draw_fair_odds REAL NOT NULL,
    external_away_fair_odds REAL NOT NULL,
    quality_score REAL NOT NULL,
    quality_level TEXT NOT NULL,
    raw_payload_hash TEXT,
    is_valid INTEGER NOT NULL,
    warnings_json TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS normalized_bookmakers (
    id TEXT PRIMARY KEY,
    external_snapshot_id TEXT NOT NULL,
    bookmaker TEXT NOT NULL,
    bookmaker_key TEXT,
    home_odds REAL,
    draw_odds REAL,
    away_odds REAL,
    home_prob REAL,
    draw_prob REAL,
    away_prob REAL,
    overround REAL,
    weight REAL,
    included INTEGER NOT NULL,
    exclusion_reason TEXT,
    last_update TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    official_match_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    official_sp_snapshot_id TEXT,
    external_odds_snapshot_id TEXT,
    recalculation_id TEXT,
    market_probability_json TEXT NOT NULL,
    external_market_probability_json TEXT NOT NULL,
    pure_model_probability_json TEXT NOT NULL,
    final_probability_json TEXT NOT NULL,
    market_fair_odds_json TEXT NOT NULL,
    external_market_fair_odds_json TEXT NOT NULL,
    pure_model_fair_odds_json TEXT NOT NULL,
    final_fair_odds_json TEXT NOT NULL,
    pure_model_edge_json TEXT,
    final_edge_json TEXT,
    ev_json TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    critic_report_json TEXT,
    stake_recommendation_json TEXT,
    probability_source TEXT,
    model_version TEXT,
    lifecycle_status TEXT,
    warnings_json TEXT
);

CREATE TABLE IF NOT EXISTS recommendations (
    id TEXT PRIMARY KEY,
    prediction_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    official_match_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    lifecycle_status TEXT NOT NULL,
    selected_probability REAL,
    selected_official_sp REAL,
    ev REAL,
    final_stake REAL,
    stake_status TEXT,
    capped_by TEXT,
    reason_json TEXT,
    warnings_json TEXT
);

CREATE TABLE IF NOT EXISTS recommendation_lifecycle_events (
    id TEXT PRIMARY KEY,
    match_id TEXT NOT NULL,
    official_match_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    previous_status TEXT,
    new_status TEXT NOT NULL,
    previous_recommendation TEXT,
    new_recommendation TEXT,
    reason TEXT NOT NULL,
    trigger_type TEXT,
    previous_ev REAL,
    new_ev REAL,
    audit_log_id TEXT
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    action TEXT NOT NULL,
    summary TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    trigger_json TEXT,
    severity TEXT NOT NULL,
    actor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bankroll_transactions (
    id TEXT PRIMARY KEY,
    bankroll_id TEXT NOT NULL,
    match_id TEXT,
    official_match_id TEXT,
    type TEXT NOT NULL,
    amount REAL NOT NULL,
    bankroll_before REAL NOT NULL,
    bankroll_after REAL NOT NULL,
    created_at TEXT NOT NULL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS model_governance_records (
    model_id TEXT PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_type TEXT NOT NULL,
    version TEXT NOT NULL,
    role TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    archived_at TEXT,
    training_match_count INTEGER,
    validation_match_count INTEGER,
    test_match_count INTEGER,
    metrics_json TEXT NOT NULL,
    baseline_model_id TEXT,
    promotion_status TEXT NOT NULL,
    promotion_reason TEXT,
    warnings_json TEXT
);

CREATE TABLE IF NOT EXISTS backtest_runs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    name TEXT,
    config_json TEXT NOT NULL,
    metrics_json TEXT,
    status TEXT NOT NULL,
    model_version TEXT,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS backtest_records (
    id TEXT PRIMARY KEY,
    backtest_run_id TEXT NOT NULL,
    match_id TEXT NOT NULL,
    official_match_id TEXT NOT NULL,
    kickoff_time TEXT NOT NULL,
    league TEXT,
    prediction_json TEXT NOT NULL,
    actual_result TEXT,
    recommendation TEXT,
    stake REAL,
    profit REAL,
    bankroll_before REAL,
    bankroll_after REAL,
    clv REAL,
    brier_score REAL,
    log_loss REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_runs (
    id TEXT PRIMARY KEY,
    task_name TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    error_message TEXT,
    affected_matches INTEGER,
    created_snapshots INTEGER,
    created_predictions INTEGER,
    warnings_json TEXT
);
