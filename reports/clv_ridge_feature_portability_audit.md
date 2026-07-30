# CLV Ridge Feature Portability Audit

## Purpose

Test whether the historical v6.2 result can transfer to prospective official-pool
matches whose league labels do not use the historical football-data division
codes.

## League Concentration

The half-Kelly v6.3 replay remained profitable after removing any single league.
The two largest positive league contributions were I2 and B1, but removing either
one left aggregate profit positive. This rejects a single-league explanation,
although multi-league concentration risk remains.

## Live Unknown-League Stress

The full v6.2 model was trained normally, but every immediate test-month league
label was replaced with an unseen value before prediction. This reproduces the
current online fallback for official-pool league labels.

| Metric | Result |
| --- | ---: |
| Folds | 16 |
| Active months | 10 |
| Bets | 97 |
| Profit | 4.81 |
| ROI | 29.64% |
| Mean closing edge | 4.4745% |
| Positive CLV | 71.13% |
| Monthly bootstrap lower 95% | -2.2217% |
| Decision | Rejected |

The nominal result stayed positive, but sample count fell below 100 and the
confidence lower bound became negative. Historical aligned-league performance
must not be treated as the expected live result.

## Portable Models

The six-month portable model removed league entirely and passed the aggregate
5% cost rolling test: 100 bets, 37.75% ROI, and a 2.6107% bootstrap lower bound.
However, its latest `2025-09..2026-02` training window failed the inner CLV gate,
so no current model could be exported.

The twelve-month portable model passed the latest inner gate, but failed the
aggregate rolling test: 77 bets, 21.70% ROI, and a -6.6732% bootstrap lower bound.
Its generated model file was deleted and cannot be loaded by production.

## Governance Decision

- Keep v6.2 and v6.3 as prospective paper-only probes.
- Do not claim their aligned historical ROI as live expected ROI.
- Do not deploy v6.4 or v6.5.
- Require a portable model to pass both aggregate rolling evidence and the latest
  training gate before registration.
- Continue collecting immutable T-1 evidence; no real order path exists.
