ALTER TABLE paper_portfolio_runs
ADD COLUMN risk_policy_hash TEXT;

ALTER TABLE paper_portfolio_runs
ADD COLUMN risk_multiplier REAL;

ALTER TABLE paper_portfolio_runs
ADD COLUMN risk_state_json TEXT;
