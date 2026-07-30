# V6.3 Half-Kelly One-Month Simulation

`2026-03` is the chronologically latest evaluated rolling month. No month was
selected by profit, and all 11 selections were frozen by v6.2 before settlement.

## Result

| Metric | Value |
| --- | ---: |
| Calendar days | 31 |
| Active days | 6 |
| Positions | 11 |
| Total invested | 8.48 |
| Net profit | 1.34 |
| ROI | 15.80% |
| Maximum daily investment | 3.79 |
| Maximum drawdown | 1.32 |
| Daily limit | 100.00 |

## Active Days

| Date | Bets | Invested | Profit/Loss | Cumulative Profit | Cash Reserved |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2026-03-06 | 1 | 0.66 | -0.66 | -0.66 | 99.34 |
| 2026-03-07 | 1 | 0.66 | -0.66 | -1.32 | 99.34 |
| 2026-03-08 | 4 | 3.79 | +0.08 | -1.24 | 96.21 |
| 2026-03-15 | 3 | 1.81 | +0.96 | -0.28 | 98.19 |
| 2026-03-19 | 1 | 0.79 | -0.79 | -1.07 | 99.21 |
| 2026-03-22 | 1 | 0.77 | +2.41 | +1.34 | 99.23 |

The complete 31-day zero-based ledger is `selected_latest_month_daily.csv`.
This staking rule was selected after historical inspection, so it is registered
only as a prospective paper challenger and cannot place real orders.
