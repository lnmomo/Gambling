# V6.2 One-Month No-Lookahead Simulation

## Selection Rule

`2026-03` is the last evaluated rolling month before the already sealed
`2026-05` month. It was selected by chronology, not by profit. The model used
only `2025-09-01..2026-02-28` for training and inner validation.

## Decision Contract

- Daily investment limit: 100
- Principal: unlimited
- Sizing: 1/10 Kelly, maximum 5 per match
- Maximum executable odds: 5.0
- Exchange cost stress: 5%
- Slippage: 2% on the profit component
- Test-month closing prices and results were absent from the decision frame
- All positions and stakes were frozen before settlement

## Result

| Metric | Value |
| --- | ---: |
| Calendar days | 31 |
| Active investment days | 6 |
| Positions | 11 |
| Total invested | 1.69 |
| Net profit | 0.25 |
| ROI | 14.79% |
| Maximum cumulative drawdown | 0.26 |
| Mean closing edge | 2.1909% |
| Positive CLV rate | 54.55% |

## Daily Capital Changes

| Date | Bets | Invested | Profit/Loss | Cumulative Profit | Reserved From Daily Limit |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-03-06 | 1 | 0.13 | -0.13 | -0.13 | 99.87 |
| 2026-03-07 | 1 | 0.13 | -0.13 | -0.26 | 99.87 |
| 2026-03-08 | 4 | 0.76 | +0.01 | -0.25 | 99.24 |
| 2026-03-15 | 3 | 0.36 | +0.19 | -0.06 | 99.64 |
| 2026-03-19 | 1 | 0.16 | -0.16 | -0.22 | 99.84 |
| 2026-03-22 | 1 | 0.15 | +0.47 | +0.25 | 99.85 |

All other March dates had no qualifying signal, zero investment, and no capital
change. The complete 31-day ledger is in `daily.csv`; individual frozen
positions and post-event settlements are in `positions.csv`.

## Evidence Status

The full 16-fold, 5% cost experiment produced 109 positions, 30.46% nominal
ROI, and a monthly bootstrap 95% lower bound of 2.7635%. This is the first
historical research survivor, but it remains post-hoc exploratory because the
fixed longshot cap was adopted after earlier fold inspection. It cannot be
promoted until prospective T-1 snapshots provide independent confirmation.
