# Profit Algorithm Findings

## Objective

Find a betting algorithm with repeatable out-of-sample edge. A profitable month is only a validation window, not the objective.

## Current Validation Standard

- Same-day match results are hidden until settlement.
- Strategy rules are fixed before monthly simulation.
- Results are judged by total profit, ROI, bet count, positive/negative active months, drawdown, and development/holdout split.
- A strategy is not production-ready if it depends on one recent month, one narrow bucket with too few bets, or a large drawdown relative to profit.

## Candidate Comparison

| Candidate | Bets | Profit | ROI | Max DD | Active Months | Positive / Negative | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| SP2 draw only | 112 | 12.86 | 10.44% | 15.17 | 28 | 16 / 12 | Best current candidate, still unstable |
| SP2 all outcomes | 130 | 11.72 | 8.30% | 15.92 | 29 | 15 / 14 | Positive but unstable |
| Rolling rule selector, medium gate | 63 | 8.06 | 15.54% | 7.41 | 17 | 9 / 8 | No lookahead, not enough bets |
| SP2 draw [2.2,2.8) | 17 | 11.63 | 44.78% | 4.95 | 11 | 7 / 4 | Too few bets |
| SP2 all outcomes, min stake 0.25 | 130 | 7.86 | 12.71% | 8.17 | 29 | 14 / 14 | Lower risk, unstable month balance |
| Rolling rule selector, loose gate | 63 | 7.27 | 12.44% | 8.92 | 17 | 9 / 8 | No lookahead, not enough bets |
| Rolling rule selector, strict gate | 49 | 4.71 | 10.62% | 6.09 | 15 | 8 / 7 | No lookahead, not enough bets |
| Adaptive SP2 selector | 34 | 2.48 | 6.89% | 10.10 | 10 | 3 / 7 | Not enough evidence |
| Balanced gate | 64 | 0.95 | 1.38% | 15.00 | 14 | 6 / 8 | Rejected |
| SP2 draw [2.8,3.5) | 94 | -0.58 | -0.61% | 16.06 | 28 | 15 / 13 | Rejected |
| Conservative gate | 51 | -3.15 | -5.95% | 15.00 | 12 | 5 / 7 | Rejected |

## Development / Holdout Check

| Candidate | Development Before 2024-06 | Holdout From 2024-06 |
| --- | --- | --- |
| SP2 draw only | 71 bets, +1.96 profit, 2.41% ROI, 10 / 8 positive-negative months | 41 bets, +10.90 profit, 26.04% ROI, 6 / 4 positive-negative months |
| SP2 all outcomes | 86 bets, -1.22 profit, -1.27% ROI, 9 / 10 positive-negative months | 44 bets, +12.94 profit, 28.85% ROI, 6 / 4 positive-negative months |
| SP2 all outcomes, min stake 0.25 | 86 bets, +3.83 profit, 8.80% ROI, 9 / 10 positive-negative months | 44 bets, +4.03 profit, 22.02% ROI, 5 / 5 positive-negative months |
| SP2 draw [2.2,2.8) | 6 bets, +9.99 profit, 70.80% ROI, 3 / 1 positive-negative months | 11 bets, +1.64 profit, 13.83% ROI, 4 / 3 positive-negative months |

## Interpretation

The current best algorithmic direction is not "bet strong teams against soft odds". The evidence points to a market-residual edge around Spanish Segunda draw pricing, especially when the model selects draw as the highest lower-bound EV outcome.

This is promising but not enough for real-money deployment. The strongest full-sample candidate, SP2 draw only, is positive in both development and holdout windows, but most of the profit comes from the later holdout period and max drawdown is larger than total profit. The narrow [2.2,2.8) bucket has attractive ROI, but 17 bets is too small to treat as a stable algorithm.

## No-Lookahead Rule Selector

A stricter rolling rule selector was added to avoid choosing the best rule after seeing the full sample. Each month, it evaluates a fixed rule pool using only prior active months, then either selects one rule for the next month or abstains.

Rule pool:

- `sp2_draw_all`
- `sp2_draw_all_min025`
- `sp2_draw_22_28`
- `sp2_draw_28_35`
- `sp2_all_min025`
- `sp2_all`

Best selector variant so far:

- Lookback: 12 active months
- Minimum active history: 4 months
- Minimum prior candidate bets: 25
- Minimum prior ROI: 2%
- Result: 63 bets, +8.06 profit, 15.54% ROI, 7.41 max drawdown, 9 positive months, 8 negative months

This is a better research signal than the fixed full-sample rules because the monthly rule choice does not use future outcomes. However, 63 bets is still below the 100-bet minimum evidence threshold, and the positive/negative month split is only slightly positive.

## Five-Season Stress Test

The candidate rules were rerun on 2022-08 through 2026-05, adding the 2025-26 season as a stricter recent-validation window. The result is weaker than the four-season view.

| Candidate | Bets | Profit | ROI | Max DD | Active Months | Positive / Negative | Latest Season | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| SP2 draw only | 113 | 11.86 | 9.55% | 15.17 | 29 | 16 / 13 | 1 bet, -1.00 | Not enough recent evidence |
| Rolling rule selector, medium gate | 64 | 7.06 | 13.35% | 7.41 | 18 | 9 / 9 | 1 bet, -1.00 | Not enough sample |
| SP2 all outcomes, min stake 0.25 | 133 | 6.68 | 10.60% | 8.17 | 31 | 14 / 16 | 3 bets, -1.18 | Not enough recent evidence |
| SP2 draw, lower EV >= -0.02 | 149 | 3.56 | 2.22% | 17.67 | 31 | 14 / 17 | 2 bets, +0.75 | Not enough recent evidence |
| SP2 draw, lower EV >= -0.05 | 418 | 18.08 | 4.21% | 20.76 | 40 | 18 / 21 | 50 bets, +1.90 | Positive but unstable |

Season split for the broadest relaxed rule (`lower_ev >= -0.05`):

| Season | Bets | Profit | ROI |
| --- | ---: | ---: | ---: |
| 2022-23 | 115 | 9.42 | 8.05% |
| 2023-24 | 104 | -6.82 | -6.42% |
| 2024-25 | 149 | 13.58 | 9.06% |
| 2025-26 | 50 | 1.90 | 3.80% |

Interpretation: relaxing the threshold increases sample size and recovers some recent activity, but it does not solve the algorithm problem. The monthly win/loss balance is still negative, drawdown exceeds total profit, and one full season remains clearly loss-making. This is not a production betting algorithm yet.

The stability assessment in `scripts/fixed_sp2_edge_strategy.py` now requires more than total profit:

- At least 100 bets.
- At least 24 active betting months.
- More positive than negative active months.
- More positive than negative seasons.
- Latest season has at least 10 bets and non-negative profit.
- Max drawdown is no larger than total profit.

## Next Research Step

Do not promote the current SP2 rules to live betting. The next experiment should search for a more robust edge family, not a better month. Candidate directions:

- Expand the rule family across leagues and odds buckets, but require walk-forward selection using only prior months.
- Add a recent-season degradation penalty so rules that disappear in 2025-26 are automatically rejected.
- Optimize for stability-adjusted return: profit is useful only if monthly balance, season balance, and drawdown survive.
- Keep the monthly validation process frozen before settlement; do not use final match results when choosing same-day bets.
