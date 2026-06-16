INSERT OR IGNORE INTO model_governance_records (
    model_id, model_name, model_type, version, role, created_at, activated_at,
    metrics_json, promotion_status, promotion_reason, warnings_json
) VALUES (
    'champion-baseline-v1',
    'Contextual Ensemble Baseline',
    'RULES_AND_STATISTICAL',
    'v1',
    'CHAMPION',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP,
    '{"source":"dev-seed","note":"sanitized governance baseline"}',
    'APPROVED',
    'Initial sanitized development champion. Does not enable challenger stacking.',
    '[]'
);
