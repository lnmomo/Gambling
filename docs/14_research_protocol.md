# ESWA Research Protocol

## Research Question

Can a leakage-controlled, market-anchored football expert system improve out-of-sample
probability quality over de-vigged bookmaker probabilities and standard football models?

Profit is not the primary endpoint. The primary endpoints are Log Loss, multiclass Brier
Score, Ranked Probability Score, top-label ECE, and classwise ECE.

## Data Contract

- Historical CSV files are hashed and audited before an experiment.
- `B365H/B365D/B365A` and equivalent fields are called pre-closing odds because the files
  do not provide exact collection timestamps.
- `B365CH/B365CD/B365CA` and equivalent fields are closing-line reference data only.
- Result and post-match columns are never supplied as model features.
- Every prediction is generated from matches strictly earlier than its fold cutoff.

## Nested Rolling-Origin Design

1. Fit time-decayed Dixon-Coles parameters only on earlier matches.
   The enhanced variant jointly estimates shrunk league goal-level and home-advantage effects.
2. Build exponentially decayed team form, goal, shot, shot-on-target, venue, rest, and
   sample-reliability features using earlier matches only. Same-day results are hidden until
   every match on that date has received its features.
3. Build model-training, calibration, and test windows in chronological order.
4. Fit market-residual parameters on the training window.
5. Select league shrinkage and temperature only on the calibration window.
6. Evaluate exactly once on the following test month.
7. Concatenate untouched test predictions across all folds.

## Baselines and Ablations

- Multiplicatively de-vigged pre-closing market.
- Time-decayed Dixon-Coles.
- Hierarchical league Dixon-Coles.
- Multinomial logistic regression.
- Random forest.
- Histogram gradient boosting.
- Fixed 75% market / 25% Dixon-Coles blend.
- Proposed market-anchored hierarchical residual model.
- Proposed model without temperature calibration.
- Proposed model without league-level residuals.
- Proposed model without leakage-free rolling football features.
- Closing market as a non-deployable reference benchmark.

## Statistical Analysis

Model comparisons use paired match-level bootstrap resampling with a fixed seed. Reports
include the Log Loss difference, 95% confidence interval, and bootstrap probability that
the proposed model is better. An interval crossing zero is reported as inconclusive.

## Reproduction

```powershell
.\.venv\Scripts\python.exe scripts\research_experiment.py `
  --source data\historical_csv\football-data `
  --output reports\research_experiment `
  --first-test-month 2024-06 `
  --test-months 12 `
  --bootstrap-samples 2000
```
