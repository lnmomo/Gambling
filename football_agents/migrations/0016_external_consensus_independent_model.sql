ALTER TABLE external_consensus_decisions
ADD COLUMN pure_model_prediction_id INTEGER REFERENCES model_predictions(id);

ALTER TABLE external_consensus_decisions
ADD COLUMN pure_model_home_probability REAL;

ALTER TABLE external_consensus_decisions
ADD COLUMN pure_model_draw_probability REAL;

ALTER TABLE external_consensus_decisions
ADD COLUMN pure_model_away_probability REAL;
