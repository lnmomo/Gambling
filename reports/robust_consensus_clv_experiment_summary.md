# Robust Consensus CLV Experiment Audit

Generated from nested monthly walk-forward research. The latest sealed complete
month (`2026-05`) is excluded from every rolling fold.

## Method

- Each fold selects a strategy using only the prior six calendar months.
- Opening prices alone create and size the next-month positions.
- Closing prices are attached only after each day's candidate set and stakes are frozen.
- Results are revealed only for settlement after the frozen decision.
- Exchange commission and 2% slippage are applied to the profit component of executable odds.
- Principal is unlimited, but the daily investment cap remains 100.

## Results

| Variant | Exchange commission | Folds | Active months | Bets | Staked | Profit | ROI | Mean CLV | Positive CLV | Bootstrap ROI lower 95% | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| v5 CLV strategy selection | 2.5% | 16 | 9 | 84 | 30.41 | -0.62 | -2.04% | 7.1222% | 73.81% | -34.3025% | Rejected |
| v5 CLV strategy selection | 5.0% | 16 | 3 | 19 | 7.07 | 1.48 | 20.93% | 6.0514% | 78.95% | -41.3333% | Rejected |
| v5.1 CLV bucket gate | 2.5% | 16 | 6 | 20 | 6.56 | 0.61 | 9.30% | 9.3446% | 85.00% | -42.0281% | Rejected |
| v5.1 CLV bucket gate | 5.0% | 16 | 1 | 2 | 0.36 | -0.01 | -2.78% | 5.1007% | 100.00% | -2.7778% | Rejected |

## Decision

Neither challenger is registered for live shadow allocation. Positive nominal
ROI at 5% in v5 and at 2.5% in v5.1 is supported by too few bets, has a negative
bootstrap lower bound, uses almost none of the available daily capital, and is
strongly concentrated in the away outcome. Scaling stake size would not repair
those evidence failures.

The next independent evidence must come from prospective T-1 snapshots with
provider timestamps and observed closing prices. These historical folds are now
exploratory evidence and must not be reused as a fresh confirmation set after
this result was inspected.

## Reproducible Artifacts

- `reports/robust_consensus_nested_monthly_v5_clv_2_5pct/rolling_nested_summary.json`
- `reports/robust_consensus_nested_monthly_v5_clv_5pct/rolling_nested_summary.json`
- `reports/robust_consensus_nested_monthly_v5_1_clv_bucket_2_5pct/rolling_nested_summary.json`
- `reports/robust_consensus_nested_monthly_v5_1_clv_bucket_5pct/rolling_nested_summary.json`
