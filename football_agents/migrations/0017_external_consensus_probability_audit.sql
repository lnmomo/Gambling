ALTER TABLE external_consensus_decisions
ADD COLUMN effective_bookmaker_count INTEGER;

ALTER TABLE external_consensus_decisions
ADD COLUMN external_home_sem REAL;

ALTER TABLE external_consensus_decisions
ADD COLUMN external_draw_sem REAL;

ALTER TABLE external_consensus_decisions
ADD COLUMN external_away_sem REAL;

ALTER TABLE external_consensus_decisions
ADD COLUMN fused_home_probability REAL;

ALTER TABLE external_consensus_decisions
ADD COLUMN fused_draw_probability REAL;

ALTER TABLE external_consensus_decisions
ADD COLUMN fused_away_probability REAL;

ALTER TABLE external_consensus_decisions
ADD COLUMN selected_probability_uncertainty REAL;
