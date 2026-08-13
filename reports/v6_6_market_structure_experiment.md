# v6.6 Market-Structure CLV Experiment

## Objective

Improve long-run paper profit without selecting a favorable calendar month. Every test month is the immediate next month after a trailing training window. Directions and stakes are frozen before closing prices and match results are attached. The daily paper-investment limit is CNY 100.

## Algorithm change

The candidate removes the league-name feature and adds opening-only nonlinear market structure terms: implied probability, executable price ratio, probability uncertainty, relative bookmaker dispersion, log odds, squared probability, probability/odds interaction, reference depth, execution-price haircut, and outcome/odds/source interaction buckets.

No actual score, result, closing price, win flag, or realized profit is available to the prediction frame.

## Rolling walk-forward evidence

| Train / validation | Cost stress | Bets | Active months | Positive months | Staked | Profit | ROI | Mean CLV | Positive CLV | Bootstrap ROI lower 95% | Gate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 6m / 2m | 2.5% | 127 | 12 | 9 | 21.67 | +8.36 | 38.58% | 5.12% | 77.17% | +5.19% | Pass research gate |
| 6m / 2m | 5.0% | 117 | 10 | 6 | 20.16 | +4.46 | 22.12% | 3.88% | 69.23% | -12.38% | Reject |
| 12m / 3m | 2.5% | 93 | 9 | 6 | 15.95 | +3.53 | 22.13% | 5.04% | 73.12% | -10.10% | Reject |
| 12m / 3m | 5.0% | 78 | 9 | 5 | 13.97 | +2.70 | 19.33% | 4.26% | 70.51% | -8.64% | Reject |

The 2.5% 6m/2m configuration is the only rolling survivor. The other three fixed robustness scenarios remain visible and prevent production promotion.

## Stake policy selected on rolling folds

The selection rule requires at least 100 bets, positive aggregate profit, a positive monthly-bootstrap lower bound, no day above CNY 100, and maximum drawdown no greater than CNY 10. Among eligible policies it maximizes profit.

| Policy | Staked | Profit | ROI | Max drawdown | Max daily stake | Bootstrap lower 95% |
|---|---:|---:|---:|---:|---:|---:|
| 0.1 Kelly | 21.67 | +8.36 | 38.58% | 1.22 | 2.61 | +5.19% |
| 0.25 Kelly | 54.31 | +20.94 | 38.56% | 3.07 | 6.52 | +5.01% |
| 0.5 Kelly | 108.66 | +41.84 | 38.51% | 6.16 | 13.05 | +5.02% |

Selected stake policy: **0.5 Kelly**. Flat stakes were rejected because their bootstrap lower bounds were negative.

## Sealed May 2026 holdout

May 2026 was excluded from algorithm and stake-policy selection. The model was trained on 2025-11-01 through 2026-04-30, decisions were frozen from opening data, and only then were May closing prices and results attached.

| Date | Bets | Staked | Daily profit | Cumulative profit | Drawdown | Unused daily budget |
|---|---:|---:|---:|---:|---:|---:|
| 2026-05-03 | 1 | 0.55 | -0.55 | -0.55 | 0.55 | 99.45 |
| 2026-05-09 | 1 | 0.58 | +1.76 | +1.21 | 0.00 | 99.42 |
| 2026-05-13 | 1 | 0.82 | -0.82 | +0.39 | 0.82 | 99.18 |
| 2026-05-17 | 2 | 1.44 | +3.09 | +3.48 | 0.00 | 98.56 |

All other May dates had zero bets and retained the full CNY 100 budget. Final sealed-month result: 5 bets, CNY 3.39 staked, CNY 3.48 profit, 102.65% ROI, and CNY 0.82 maximum drawdown. This is a very small sample and is not sufficient evidence of repeatable profitability.

## Deployment decision

The frozen model is registered only as `clv-ridge-v6.6-market-structure-half-kelly-prospective-shadow`. It never creates real orders. Its API warning records both unresolved risks: the 5% transaction-cost stress failed and retraining through 2026-05-31 failed the inner CLV gate. Promotion remains blocked until new timestamp-aligned T-1 observations are settled.

## Subsequent v7 robustness experiments

These candidates reuse the same fixed rolling months; May is no longer described as unseen for algorithms developed after the v6.6 holdout was inspected.

| Candidate | Cost | Bets | Profit | ROI | Bootstrap lower 95% | Decision |
|---|---:|---:|---:|---:|---:|---|
| v7 closing-probability target | 2.5% | 140 | +3.64 | 15.78% | -10.76% | Reject |
| v7 closing-probability target | 5.0% | 125 | +2.90 | 14.08% | -15.96% | Reject |
| v7.1 probability-movement target | 2.5% | 128 | +4.60 | 21.01% | -5.38% | Reject |
| v7.1 probability-movement target | 5.0% | 138 | +4.74 | 19.64% | -2.12% | Reject |
| v7.2 one-sided residual calibration | 2.5% / 5.0% | 0 | 0.00 | 0.00% | unavailable | Reject: abstains everywhere |
| v7.3 prior-validation profit regime gate | 2.5% | 85 | +3.42 | 23.98% | -24.08% | Reject |
| v7.3 prior-validation profit regime gate | 5.0% | 100 | +2.21 | 12.33% | -28.17% | Reject |
| v7.4 v6.6/v7.1 model agreement, 0.5 Kelly | 2.5% | 102 | +25.67 | 29.39% | +2.09% | Research survivor |
| v7.4 v6.6/v7.1 model agreement, 0.5 Kelly | 5.0% | 113 | +24.51 | 25.21% | -7.78% | Reject |

The agreement rule removes future fields before intersecting the independently frozen selections, uses the lower of the two predicted CLV margins, freezes the stake, and merges outcomes only for settlement. Its daily maximum was CNY 11.71 at 2.5% costs and CNY 8.51 at 5% costs, both below the CNY 100 limit. Because the high-cost confidence bound remains negative, v7.4 is not registered as a new online shadow policy.

## Corrected archived-month coverage and v7.6

The original month detector incorrectly required a football match on both the first and final calendar day. The corrected archive rule accepts every immutable historical month with at least 100 matches, while the newest archive month must still reach its calendar end. This expanded the fixed evaluation from 16 to 19 natural months; the local summer fragments contain only 8-10 matches and remain excluded.

| Candidate | Cost | Folds | Bets | Positive active months | Profit | ROI | Bootstrap lower 95% |
|---|---:|---:|---:|---:|---:|---:|---:|
| v6.6 direct CLV | 2.5% | 19 | 156 | 11 / 15 | +12.20 | 46.41% | +9.52% |
| v6.6 direct CLV | 5.0% | 19 | 132 | 7 / 12 | +7.28 | 31.67% | -7.75% |
| v7.1 probability movement | 2.5% | 19 | 165 | 7 / 14 | +7.77 | 28.01% | -3.01% |
| v7.1 probability movement | 5.0% | 19 | 159 | 9 / 13 | +7.61 | 27.27% | -1.60% |
| v7.6 model agreement, 0.5 Kelly | 2.5% | 19 | 130 | 10 / 14 | +45.36 | 41.31% | +5.69% |
| v7.6 model agreement, 0.5 Kelly | 5.0% | 19 | 128 | 7 / 12 | +38.75 | 34.78% | -4.35% |

v7.6 is registered as a sixth **paper-only** prospective policy so new T-1 evidence can resolve the remaining uncertainty. It combines frozen v6.6 and v7.1 JSON models trained through 2026-04-30, requires both models to clear the 1% lower-CLV gate, and stakes from the lower estimate. Training through 2026-05-31 failed the inner gate and was not exported. The policy cannot place real orders and remains ineligible for promotion while its 5% cost confidence bound is negative.

## v8 expanded named-book archive

The older 2021-22 through 2023-24 CSV files were already archived, but their common `IW` (Interwetten) and `VC` (VCBet) columns were not part of the named-book parser. Adding those two recognized bookmakers, without reducing the requirement of five valid opening books and four leave-one-out references, expands the usable archive to 32,969 matches and 48 rolling evaluation months from July 2021 through May 2026.

| Candidate | Cost | Folds | Bets | Positive active months | Staked | Profit | ROI | Bootstrap lower 95% | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Direct CLV | 2.5% | 48 | 335 | 20 / 30 | 85.05 | +28.86 | 33.93% | +10.95% | Research survivor |
| Direct CLV | 5.0% | 48 | 294 | 15 / 26 | 76.35 | +17.38 | 22.76% | +0.15% | Reject: positive-month rate below 60% |
| Probability movement | 2.5% | 48 | 330 | 17 / 29 | 86.06 | +27.56 | 32.02% | +12.38% | Reject: positive-month rate below 60% |
| Probability movement | 5.0% | 48 | 308 | 19 / 28 | 83.47 | +26.52 | 31.77% | +12.54% | Research survivor |
| Dual-target agreement, 0.5 Kelly | 2.5% | 48 | 266 | 19 / 26 | 349.15 | +135.11 | 38.70% | +18.45% | Research survivor |
| Dual-target agreement, 0.5 Kelly | 5.0% | 48 | 248 | 15 / 23 | 334.28 | +107.99 | 32.31% | +12.31% | Research survivor |

The agreement replay's maximum historical daily stake was CNY 28.11, below the CNY 100 limit, and its maximum drawdown was CNY 22.21. Its larger stake total than the individual model rows is expected because agreement uses the previously frozen 0.5-Kelly challenger while individual diagnostics use 0.1 Kelly.

This is stronger retrospective evidence, not a profitability guarantee. Both component models failed the unchanged inner-validation gate when retrained through 2026-05-31, so no v8 artifact or runtime policy was exported. The existing v7.6 paper policy remains unchanged; only genuinely new timestamp-aligned prospective observations may qualify a later version.

## v8.1 longer validation horizon

The expanded archive showed why the 6m/2m candidate could not retrain through May 2026. At validation sizes above 30, the direct and movement models reached only 52.3% and 53.2% positive CLV; their higher-confidence slices reached 58-60% but contained only 10-12 positions. The gate therefore rejected insufficiently reliable evidence instead of merely suppressing bets.

The next candidate changes the temporal estimator, not the evaluated month: nine trailing months train the model and the last three of those months form the inner validation window. This is the shortest tested window for which both targets pass the latest unchanged gate.

| Candidate | Cost | Folds | Bets | Positive active months | Staked | Profit | ROI | Bootstrap lower 95% | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Direct CLV 9m/3m | 2.5% | 48 | 316 | 17 / 30 | 80.60 | +24.27 | 30.11% | +3.88% | Reject: positive-month rate below 60% |
| Direct CLV 9m/3m | 5.0% | 48 | 276 | 18 / 29 | 74.72 | +23.79 | 31.84% | +5.30% | Research survivor |
| Probability movement 9m/3m | 2.5% | 48 | 328 | 21 / 32 | 87.10 | +26.88 | 30.86% | +6.69% | Research survivor |
| Probability movement 9m/3m | 5.0% | 48 | 309 | 24 / 33 | 84.65 | +24.01 | 28.36% | +4.08% | Research survivor |
| Dual-target agreement 9m/3m, 0.5 Kelly | 2.5% | 48 | 267 | 18 / 28 | 355.51 | +120.58 | 33.92% | +5.55% | Research survivor |
| Dual-target agreement 9m/3m, 0.5 Kelly | 5.0% | 48 | 241 | 20 / 28 | 339.33 | +113.97 | 33.59% | +4.92% | Research survivor |

Both immutable v8.1 component models were trained on 2025-09-01 through 2026-05-31 and passed export parity. Their hashes are `66aaafb97bf5ef4eb6c17e1b294575b862fe00f1ce89ef4c64873079e980d217` and `58bbdad5955dacb0f919484dd49602065a3361b4ebed5775163526c6ee22af26`. The combined policy remains paper-only because all historical folds were available during development.

## One-month sealed replay

For the May 2026 replay, each component used only the nine months ending 2026-04-30. Directions and half-Kelly stakes were intersected and frozen before closing odds and results were merged. Principal is treated as unlimited, but each calendar day is capped at CNY 100.

| Date | Bets | Staked | Daily profit | Cumulative profit | Drawdown | Unused daily budget |
|---|---:|---:|---:|---:|---:|---:|
| 2026-05-03 | 2 | 1.11 | -1.11 | -1.11 | 1.11 | 98.89 |
| 2026-05-09 | 1 | 0.57 | +1.73 | +0.62 | 0.00 | 99.43 |
| 2026-05-13 | 1 | 0.96 | -0.96 | -0.34 | 0.96 | 99.04 |
| 2026-05-17 | 1 | 0.62 | +2.01 | +1.67 | 0.00 | 99.38 |

The remaining 27 days placed no bet and preserved the full CNY 100 daily capacity. The month ended with 5 bets, CNY 3.26 staked, CNY 1.67 profit, 51.23% ROI, and CNY 1.11 maximum drawdown. It is a profitable realization but is explicitly rejected as evidence (`bets<100`, `active_months<8`, and no usable monthly-bootstrap lower bound). It must not be presented as proof that the strategy is profitable.

## v8.2 reference-depth exclusion

A post-hoc quality decomposition found that the 48 agreement positions with only four leave-one-out reference bookmakers had a 54.2% positive-CLV rate and approximately zero profit. Requiring five references is a market-depth rule available before kickoff, but full exclusion reduced temporal coverage too aggressively. At 2.5% costs the agreement candidate produced 186 bets, 14 positive months out of 24, CNY 105.99 profit, and a +9.39% bootstrap lower bound; the 58.3% positive-month rate failed the unchanged 60% gate. v8.2 was rejected and was not registered online.

## v8.3 evidence-depth stake discount

Instead of deleting minimum-depth opportunities, v8.3 keeps the v8.1 direction and CLV gates but multiplies half-Kelly stake by 0.5 when exactly four reference bookmakers remain after excluding the execution book. This factor uses opening evidence only and is frozen before settlement.

| Candidate | Cost | Bets | Positive active months | Staked | Profit | ROI | Bootstrap lower 95% | Max drawdown | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| v8.1 agreement | 2.5% | 267 | 18 / 28 | 355.51 | +120.58 | 33.92% | +5.55% | 28.26 | Survivor |
| v8.3 depth discount | 2.5% | 267 | 17 / 28 | 337.15 | +120.70 | 35.80% | +6.77% | 26.72 | Survivor |
| v8.1 agreement | 5.0% | 241 | 20 / 28 | 339.33 | +113.97 | 33.59% | +4.92% | 28.26 | Survivor |
| v8.3 depth discount | 5.0% | 241 | 18 / 28 | 318.04 | +113.99 | 35.84% | +6.73% | 26.72 | Survivor |

The rule improves cost-stressed confidence and drawdown while preserving every frozen selection. It is registered only as an eighth prospective paper policy and shares v8.1's immutable model hashes.

### v8.3 May replay

| Date | Bets | Staked | Daily profit | Cumulative profit | Drawdown | Unused daily budget |
|---|---:|---:|---:|---:|---:|---:|
| 2026-05-03 | 2 | 0.55 | -0.55 | -0.55 | 0.55 | 99.45 |
| 2026-05-09 | 1 | 0.57 | +1.73 | +1.18 | 0.00 | 99.43 |
| 2026-05-13 | 1 | 0.48 | -0.48 | +0.70 | 0.48 | 99.52 |
| 2026-05-17 | 1 | 0.62 | +2.01 | +2.71 | 0.00 | 99.38 |

The same five pre-result selections produced CNY 2.22 staked, CNY 2.71 profit, 122.07% ROI, and CNY 0.55 maximum drawdown. The favorable outcome is not a promotion criterion; the one-month report remains rejected for insufficient sample size.

## v8.4 disagreement penalty

A fixed penalty of `0.5 * abs(direct_CLV - movement_CLV)` was subtracted before selection and combined with the v8.3 depth discount. It reduced maximum drawdown from CNY 26.72 to CNY 25.79, but also reduced 2.5%/5% profit to CNY 116.15/CNY 108.86 and bootstrap lower bounds to +6.51%/+6.39%. Because it weakened the primary confidence evidence, v8.4 was rejected and not registered.

## v8.5 inner month-stability gate

The prior inner gate pooled all three validation months. A high-volume or unusually strong month could therefore hide a negative month. v8.5 first computes mean CLV separately for each validation month and permits a fitted model only when at least 60% of those months are positive. For a three-month validation window this means at least two positive months. The rule uses only the trailing training/validation period and never reads the next test month.

| Candidate | Cost | Bets | Positive active months | Staked | Profit | ROI | Bootstrap lower 95% | Max drawdown | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| v8.3 depth discount | 2.5% | 267 | 17 / 28 | 337.15 | +120.70 | 35.80% | +6.77% | 26.72 | Survivor |
| v8.5 month-stable + depth discount | 2.5% | 234 | 16 / 26 | 302.58 | +121.60 | 40.19% | +15.53% | 21.27 | Survivor |
| v8.3 depth discount | 5.0% | 241 | 18 / 28 | 318.04 | +113.99 | 35.84% | +6.73% | 26.72 | Survivor |
| v8.5 month-stable + depth discount | 5.0% | 214 | 17 / 26 | 288.71 | +123.69 | 42.84% | +18.54% | 21.27 | Survivor |

Both v8.5 components also passed the unchanged latest-window gate through 2026-05-31. Their immutable hashes are `cc20de9f769520b7525e5c6b28fb4ebee0f2ea32b5f2b96c190b4597526af03f` and `703ad1abce278c1b842cdb17b42c0fbfd6801a3dd6a6c6cdb3afe0352766624d`. v8.5 replaces v8.3 in the active eight-policy experiment; the immutable v8.3 database history is retained.

The May 2026 sealed replay remains five selections, CNY 2.22 staked, CNY 2.71 profit, and CNY 0.55 maximum drawdown because the two prior-only component gates both pass for that month. It remains an insufficient single-month sample and has no role in promotion.

## v8.6 validation Platt staking calibration

On the 234 v8.5 agreement positions, the lower-CLV Kelly probability had Brier score 0.21542, compared with 0.21444 for opening consensus and 0.21138 for the observed closing market. v8.6 therefore fitted a regularized one-dimensional Platt calibrator from each fold's prior validation predictions to prior outcomes. Selection remained CLV-only; only the frozen Kelly probability changed.

The calibrator increased 2.5%/5% nominal profit to CNY 152.01/CNY 143.88, but only 13 of 24 active months were profitable in both cases. Bootstrap lower bounds fell to +5.98%/+6.57% and maximum drawdown increased to CNY 24.73. All six direct, movement, and agreement scenarios failed at least one unchanged gate. v8.6 was rejected and not exported online.

## v8.7 minimum conservative probability

The lowest v8.5 probability quintile predicted 22.7% wins but realized 14.9%, consistent with a longshot-calibration problem. v8.7 keeps the v8.5 model, month gate, agreement rule, and depth discount, while requiring the pre-result conservative staking probability to be at least 25%.

| Candidate | Cost | Bets | Positive active months | Staked | Profit | ROI | Bootstrap lower 95% | Max drawdown | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| v8.5 | 2.5% | 234 | 16 / 26 | 302.58 | +121.60 | 40.19% | +15.53% | 21.27 | Survivor |
| v8.7 minimum 25% | 2.5% | 173 | 15 / 24 | 265.13 | +120.21 | 45.34% | +19.11% | 19.47 | Survivor |
| v8.5 | 5.0% | 214 | 17 / 26 | 288.71 | +123.69 | 42.84% | +18.54% | 21.27 | Survivor |
| v8.7 minimum 25% | 5.0% | 166 | 16 / 24 | 260.52 | +120.00 | 46.06% | +18.57% | 19.47 | Survivor |

At 2.5% costs, away selections fall from 116 of 234 under the earlier agreement sample to 51 of 173, while home/draw/away counts become 72/50/51. v8.7 is registered beside v8.5 as a ninth paper-only policy because it improves calibration robustness and drawdown but slightly reduces aggregate historical profit.

The May sealed replay contains one pre-result selection on 2026-05-09: CNY 0.28 staked, CNY 0.85 profit, and no drawdown. This tiny realization is rejected as evidence and is reported only to preserve the requested daily process.

## v8.8 five-eighths Kelly challenger

After the v8.7 longshot filter, the remaining 173 positions had a 36.8% mean frozen staking probability and a 42.8% realized win rate. Because Brier score still trailed opening consensus, v8.8 makes only one pre-registered sizing change: Kelly fraction increases from 0.50 to 0.625 while the CNY 15 single-position cap and CNY 100 daily cap remain unchanged.

| Candidate | Cost | Bets | Staked | Profit | ROI | Bootstrap lower 95% | Max drawdown | Max daily stake | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| v8.7 half Kelly | 2.5% | 173 | 265.13 | +120.21 | 45.34% | +19.11% | 19.47 | 25.22 | Survivor |
| v8.8 5/8 Kelly | 2.5% | 173 | 328.83 | +152.92 | 46.50% | +20.44% | 21.76 | 28.95 | Survivor |
| v8.7 half Kelly | 5.0% | 166 | 260.52 | +120.00 | 46.06% | +18.57% | 19.47 | 25.22 | Survivor |
| v8.8 5/8 Kelly | 5.0% | 166 | 323.03 | +152.69 | 47.27% | +20.04% | 21.76 | 28.95 | Survivor |

v8.8 increases aggregate historical profit while preserving both cost-stress gates and using less than 29% of the daily limit on the busiest historical day. It is a paper-only stake challenger beside v8.7; it does not replace the half-Kelly control before prospective evidence matures.

The May sealed replay retains the same single 2026-05-09 selection. Stake rises from CNY 0.28 to CNY 0.35 and settled profit from CNY 0.85 to CNY 1.06. The month remains rejected as evidence because it contains only one position.

## Temporal-dependence stress test

The ordinary monthly bootstrap assumes independent months. A circular moving-block bootstrap now samples contiguous three-month blocks before computing portfolio ROI, preserving short-run market-regime dependence. This metric is a hard research gate for subsequent agreement replays.

| Cost | IID bootstrap lower 95% | 3-month block lower 95% | Block median | Block upper 95% | Decision |
|---|---:|---:|---:|---:|---|
| 2.5% | +20.44% | +19.71% | 46.03% | 70.66% | Pass |
| 5.0% | +20.04% | +18.31% | 46.67% | 74.16% | Pass |

The latest 2025-26 historical segment is weaker in realized profit (+CNY 3.71 at 2.5% costs and -CNY 2.08 at 5% costs), but its mean CLV remains +6.50%/+8.69% with 76.7%/75.0% positive CLV. This is treated as unresolved outcome variance rather than proof of edge decay. v8.8 remains at 0.625 Kelly and will not be increased again without prospective evidence.

## v8.9 exchange-source and provider-dependence stress

Football-Data's official field key distinguishes `BF` (Betfair) from `BFE` (Betfair Exchange). The production interpretation therefore remains unchanged: commission applies to `BFE` only. To test whether this classification or the four unusually profitable `BF` selections inflated the result, v8.9 deliberately applies the configured exchange commission to both `BF` and `BFE`, then retrains both 9m/3m components and reruns the frozen v8.8 agreement and staking rules.

| Stress | Bets | Staked | Profit | ROI | IID lower 95% | 3-month block lower 95% | Max drawdown | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| BF+BFE at 2.5% | 170 | 329.33 | +146.91 | 44.61% | +18.83% | +18.03% | 21.76 | Survivor |
| BF+BFE at 5.0% | 171 | 322.16 | +139.66 | 43.35% | +17.00% | +14.23% | 21.76 | Survivor |

Removing all `BF` executions after the frozen replay still leaves CNY 128.68 profit and a +13.87% block-bootstrap lower bound at 2.5% costs; at 5% costs it leaves CNY 122.98 and +10.21%. The agreement replay now also applies a hard leave-one-execution-source-out diagnostic. Across all ten observed execution sources, the worst lower bound is +11.24% at 2.5% costs and +6.39% at 5% costs, so no single bookmaker is necessary for the retrospective confidence result.

The recent 2025-26 segment remains mixed: +CNY 3.09 at 2.5% stress and -CNY 2.93 at 5% stress, despite positive-CLV rates of 76.0% and 78.6%. This reinforces the existing decision: v8.9 is a robustness audit, not a new promoted strategy; v8.8 remains paper-only at 0.625 Kelly and its size is not increased.

## v8.10 executable-quote sanity correction

Profit attribution exposed stale or misaligned named-book rows that cannot be treated as executable edges. One example listed most home prices near 1.66-1.73 while a single WH row reported 3.25. The earlier algorithm selected the isolated quote because it maximized conservative EV. v8.10 rejects a quote before model training when net executable odds multiplied by leave-one-out consensus probability exceeds 1.15. The threshold is a fixed data-validity guard, not a result-selected month filter.

Both components were retrained from scratch with the quote guard, `BF` and `BFE` both charged exchange commission as an additional worst-case assumption, and every test-month decision remained frozen before closing odds and results were joined.

| Cost | Agreement bets | Positive active months | Staked | Profit | ROI | IID lower 95% | 3-month block lower 95% | Leave-one-source minimum | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 147 | 14 / 24 | 228.38 | +62.02 | 27.16% | +2.95% | +9.28% | +1.70% | Reject: positive-month rate 58.3% |
| 5.0% | 137 | 15 / 24 | 217.22 | +64.93 | 29.89% | +6.01% | +14.37% | +7.26% | Research survivor |

The large fall from v8.8's 47% ROI confirms that its historical return was materially inflated by invalid quote gaps. The v8.8 online shadow configuration now applies the same 1.15 quote-sanity limit and explicitly marks its previous unfiltered evidence as invalidated. No v8.10 model is promoted because the lower-cost path fails the unchanged monthly-stability gate and all v8.10 analysis is post-development historical research.

### Fixed May 2026 simulation

For this fixed calendar month, each component trains only through April 30. Directions and stakes are frozen from opening information, then outcomes are attached for settlement. The conservative 5% cost assumption, CNY 100 daily cap, 0.625 Kelly fraction, CNY 15 single cap, 25% minimum probability and depth discount all remain unchanged.

| Date | Bets | Staked | Daily profit | Month cumulative | Month drawdown | Unused daily budget |
|---|---:|---:|---:|---:|---:|---:|
| 2026-05-09 | 2 | 1.48 | +3.25 | +3.25 | 0.00 | 98.52 |
| 2026-05-10 | 1 | 0.74 | -0.74 | +2.51 | 0.74 | 99.26 |
| 2026-05-17 | 2 | 1.76 | +3.50 | +6.01 | 0.00 | 98.24 |

The other 28 days place no bet and retain the full CNY 100 capacity. The month ends with 5 bets, CNY 3.98 staked, CNY 6.01 profit, 151.01% realized ROI and CNY 0.74 maximum drawdown. This is a lucky, tiny realization and is rejected as profitability evidence. `monthly_daily.csv` resets cumulative profit and drawdown at each month boundary so the May curve no longer inherits prior months' profit.

## v8.11 minimum 2% conservative CLV margin

After quote cleaning, the 5% cost positions with only 1-2% frozen lower CLV lost CNY 2.43 across 11 selections. A fixed 2% entry margin is used as residual execution-noise protection; it is applied to frozen pre-result model outputs and is evaluated across all rolling months rather than selected from the May outcome.

| Cost | Bets | Positive active months | Staked | Profit | ROI | IID lower 95% | 3-month block lower 95% | Leave-one-source minimum | Max drawdown | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 133 | 15 / 24 | 216.63 | +61.74 | 28.50% | +4.10% | +10.69% | +2.78% | 10.71 | Survivor |
| 5.0% | 126 | 15 / 24 | 207.66 | +67.36 | 32.44% | +9.13% | +17.25% | +9.79% | 10.71 | Survivor |

Relative to v8.10, the rule restores the lower-cost monthly-stability pass, raises the 5% profit from CNY 64.93 to CNY 67.36, and reduces maximum drawdown from CNY 11.52 to CNY 10.71. The quote-clean direct and movement artifacts were trained through 2026-04-30 with hashes `24a04830f811281b4d81e77f1a929064397ae15fe337d15f4490c057ad7aa29d` and `e5a2eab533496a17d2da244042f60fb7f665d150993e6c8e60b6c474fe4cca17`. Their JSON export parity errors are below `5e-14`.

Retraining the direct component through 2026-05-31 failed the unchanged inner month-stability gate. v8.11 is therefore registered only as an eleventh paper policy using the April-frozen artifacts; it cannot promote or place real orders.

### v8.11 May replay

| Date | Bets | Staked | Daily profit | Month cumulative | Month drawdown | Unused daily budget |
|---|---:|---:|---:|---:|---:|---:|
| 2026-05-09 | 1 | 0.76 | +2.31 | +2.31 | 0.00 | 99.24 |
| 2026-05-10 | 1 | 0.74 | -0.74 | +1.57 | 0.74 | 99.26 |
| 2026-05-17 | 2 | 1.76 | +3.50 | +5.07 | 0.00 | 98.24 |

The fixed month contains four positions, CNY 3.26 staked and CNY 5.07 profit. Its favorable 155.52% realized ROI is a tiny-sample outcome and has no role in the policy decision.

## v8.12 extended 18m/9m stability window

The quote-clean models could not retrain through May under the 9m/3m window. Diagnostics showed a real tradeoff: zero residual margin produced 44-63 selections but only 45-52% positive CLV, while a 0.25 residual margin produced 57-62% positive CLV but only 7-14 selections. A 12m/6m window improved the high-confidence positive-CLV rate to 73-81% but still produced only 26-27 selections, below the unchanged 30-position gate. No gate was relaxed.

The v8.12 probe therefore uses 18 training months and nine validation months. Both latest-window components pass the original sample, positive-CLV and monthly-stability requirements through 2026-05-31. Full 48-month rolling evaluation then applies the same quote guard, 2% agreement margin and staking rules as v8.11.

| Cost | Bets | Positive active months | Staked | Profit | ROI | IID lower 95% | Block lower 95% | Leave-one-source minimum | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 101 | 18 / 27 | 119.50 | +39.94 | 33.42% | +7.43% | +9.73% | -0.75% | Reject: source-dependence gate |
| 5.0% | 84 | 15 / 20 | 126.36 | +44.65 | 35.34% | +15.17% | +16.24% | +3.12% | Reject: fewer than 100 bets |

The longer window resolves current retraining but materially reduces sample size and makes the lower-cost result dependent on the 1XB execution source. It is rejected and not registered online; v8.11 remains the active challenger.

### v8.12 May replay

| Date | Bets | Staked | Daily profit | Month cumulative | Month drawdown | Unused daily budget |
|---|---:|---:|---:|---:|---:|---:|
| 2026-05-09 | 1 | 0.70 | +2.13 | +2.13 | 0.00 | 99.30 |
| 2026-05-17 | 2 | 1.65 | +3.48 | +5.61 | 0.00 | 98.35 |

The fixed month has three positions, CNY 2.35 staked and CNY 5.61 profit. This tiny favorable realization does not override either full-history rejection reason.

## v8.13 three-quarter Kelly challenger

The strict single-model fallback was abandoned before implementation because only four pre-result candidates occurred in months where the direct component was unavailable; broadening it would admit model disagreements. v8.13 instead preserves every v8.11 selection and quality gate and changes only the Kelly fraction from 0.625 to 0.75. Pre-registered risk limits require both cost paths to survive, historical maximum drawdown below CNY 15 and maximum daily stake below CNY 50.

| Cost | Bets | Staked | Profit | ROI | Block lower 95% | Leave-one-source minimum | Max drawdown | Max daily stake | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 133 | 259.99 | +74.03 | 28.47% | +10.68% | +2.76% | 12.84 | 16.77 | Survivor |
| 5.0% | 126 | 249.18 | +80.64 | 32.36% | +17.22% | +9.67% | 12.84 | 16.77 | Survivor |

At 5% costs, absolute historical profit increases from v8.11's CNY 67.36 to CNY 80.64 while the maximum drawdown rises from CNY 10.71 to CNY 12.84. ROI remains effectively unchanged, as expected from a sizing-only experiment. All predefined limits pass, so v8.13 is registered beside v8.11 as a paper-only stake challenger; it cannot place real orders.

### v8.13 May replay

| Date | Bets | Staked | Daily profit | Month cumulative | Month drawdown | Unused daily budget |
|---|---:|---:|---:|---:|---:|---:|
| 2026-05-09 | 1 | 0.91 | +2.76 | +2.76 | 0.00 | 99.09 |
| 2026-05-10 | 1 | 0.88 | -0.88 | +1.88 | 0.88 | 99.12 |
| 2026-05-17 | 2 | 2.12 | +4.23 | +6.11 | 0.00 | 97.88 |

The fixed month retains four selections, stakes CNY 3.91 and realizes CNY 6.11 profit. This remains insufficient evidence and does not affect registration or promotion gates.

## v8.14 short-odds exposure audit

Profit attribution found that the 16 selections with net odds from 1.5 to 2.0 used CNY 81.44 of the 5% cost portfolio but produced only CNY 0.92 profit. The issue is not an obvious probability-calibration failure: their frozen conservative probability averaged 56.92% and the realized win rate was 56.25%. Rather, small probability errors at short odds generated relatively large Kelly stakes with little realized return. The first 70 chronological selections returned 2.80% in this band, while the later locked 56-selection segment returned -25.79%.

Three result-independent sizing candidates were evaluated. All preserve the v8.13 selection rule and use only opening odds to alter stake before outcomes are attached.

| Candidate | Cost | Bets | Staked | Profit | ROI | Block lower 95% | Leave-one-source minimum | Max drawdown | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Remove odds below 2.0 | 2.5% | 117 | 178.91 | +72.68 | 40.62% | +8.48% | -7.39% | 10.44 | Reject |
| Remove odds below 2.0 | 5.0% | 110 | 167.74 | +79.72 | 47.53% | +20.35% | +4.49% | 9.09 | Survivor only at this cost |
| Quarter stake below 2.0 | 2.5% | 133 | 199.20 | +73.02 | 36.66% | +9.81% | -3.98% | 8.23 | Reject |
| Quarter stake below 2.0 | 5.0% | 126 | 188.11 | +79.95 | 42.50% | +20.52% | +7.72% | 8.23 | Survivor only at this cost |
| Half stake below 2.0 | 2.5% | 133 | 219.45 | +73.33 | 33.42% | +11.01% | -1.18% | 8.50 | Reject |
| Half stake below 2.0 | 5.0% | 126 | 208.46 | +80.16 | 38.45% | +20.24% | +9.78% | 8.50 | Survivor only at this cost |

All three candidates improve nominal ROI and drawdown, but all fail the unchanged 2.5% leave-one-execution-source gate after excluding WH. They are rejected rather than tuned continuously against the same outcomes. v8.13 remains the prospective challenger unchanged.

The replay now also reports leave-one-league, leave-one-outcome and leave-one-odds-band diagnostics. A league is treated like a provider-dependence risk and must retain a positive moving-block lower bound when removed. Outcomes and odds bands are broader structural strata; removing one must leave positive aggregate profit, while their bootstrap values remain diagnostic because the resulting sparse monthly subsets are not independent strategy replicas. Under these rules, v8.13 remains a survivor at both costs: its minimum leave-one-league block lower bound is +1.33%/+6.05%, and no single outcome or odds band accounts for all aggregate profit.

## v8.15 prior-only selected-sample probability blend

The selected-position opening consensus had a slightly better binary Brier score than the frozen lower-CLV Kelly probability: 0.22557 versus 0.22631 at 2.5% costs and 0.23082 versus 0.23205 at 5% costs. v8.15 therefore estimated a closed-form blend weight from strictly earlier settled agreement positions, with a 30-position minimum and 50-position shrinkage prior. The current month and all later outcomes were excluded from each fit.

After the minimum sample was reached, the estimated CLV-probability weight collapsed to zero, making the opening consensus the Kelly probability. This increased 5% historical profit to CNY 104.85, but the 2.5% path had only 14 positive months out of 24 and failed the unchanged 60% month-stability gate. The candidate was rejected. The behavior also showed that this was not conservative shrinkage: consensus probability was usually above the lower-CLV probability, so exposure increased.

## v8.16 three-percent CLV margin

A single pre-specified 3% lower-CLV threshold was tested without a threshold grid. At 2.5% costs it retained exactly 100 bets, produced CNY 74.55 profit and passed the gates. At 5% costs it retained only 92 bets with 14 of 24 positive months, failing both sample and stability requirements. v8.16 was rejected and not registered.

## v8.18 broad-market outcome calibration

The earlier v8.6 Platt experiment fitted lower-CLV probability on only the short inner validation period. v8.18 instead fits a regularized logistic calibration from opening consensus probability to match outcome using every broad candidate in the trailing nine-month training window. CLV models still determine eligibility; the calibrated probability is an independent side-channel used only for final Kelly sizing.

An initial v8.17 implementation allowed calibration to affect each component model's minimum stake and consequently changed the direct/movement intersection. That evidence is invalidated. v8.18 preserves the original component selections, the 25% minimum conservative probability, and the 2% lower-CLV eligibility threshold, then applies calibrated probability only after the dual-model agreement is frozen.

| Cost | Bets | Positive months | Staked | Profit | ROI | IID lower 95% | Block lower 95% | Leave-one-source minimum | Leave-one-league minimum | Max drawdown | Max daily | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 118 | 15 / 24 | 358.65 | +114.24 | 31.85% | +7.44% | +15.94% | +5.47% | +1.51% | 22.29 | 27.92 | Survivor |
| 5.0% | 108 | 16 / 24 | 333.57 | +119.44 | 35.81% | +11.17% | +21.39% | +12.45% | +6.44% | 22.29 | 27.92 | Survivor |

Relative to v8.13, v8.18 raises 5% absolute historical profit from CNY 80.64 to CNY 119.44 while preserving positive confidence bounds and provider/league robustness. Maximum drawdown rises from CNY 12.84 to CNY 22.29. Before online shadow registration, governance limits were fixed at CNY 25 historical drawdown and CNY 50 maximum daily stake; these are post-analysis deployment controls, not pre-registered experimental evidence. The hard CNY 100 daily budget remains unchanged. v8.18 is registered only as a thirteenth paper policy and cannot place real orders.

The frozen April artifacts have hashes `43bb6ed2fb1788262f14c8cac93f8836d13efd47b895199946252f1fa4716d70` and `9d6300fb96f39cfcac31b3f339c400d6f4b6bd51114bfa1fa243ef7767d52e87`. Their shared market calibrator has intercept `0.1794335`, slope `1.2673564`, and export parity errors below `3e-14`.

### v8.18 May replay

| Date | Match | Direction | Odds | Stake | Daily profit | Month cumulative |
|---|---|---|---:|---:|---:|---:|
| 2026-05-10 | Volos NFC vs Levadeiakos | Home | 2.813 | 1.81 | -1.81 | -1.81 |
| 2026-05-17 | Trabzonspor vs Genclerbirligi | Away | 2.421 | 6.32 | +8.98 | +7.17 |

The fixed month trains both CLV components and the outcome calibrator only through April 30. It places two bets, stakes CNY 8.13, earns CNY 7.17 and never reads May outcomes before directions and stakes are frozen. This favorable two-bet realization is reported for process fidelity and is not promotion evidence.

## v8.19 validation-weighted market blend

The v8.18 calibration improves Brier score only modestly and its ten largest winning positions exceed aggregate net profit because losses offset part of those gains. v8.19 therefore fits the market calibrator on the first six months of each training window, estimates the optimal blend between lower-CLV and calibrated-market probability on the following three validation months, shrinks that weight by validation sample size, then refits the calibrator on all nine prior months. No test-month result enters either coefficient or blend-weight estimation.

| Cost | Bets | Staked | Profit | ROI | Block lower 95% | Leave-one-source minimum | Leave-one-league minimum | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 132 | 334.99 | +96.92 | 28.93% | +13.76% | +1.99% | -0.49% | Reject |
| 5.0% | 123 | 321.62 | +103.19 | 32.08% | +18.16% | +10.24% | +3.59% | Survivor only at this cost |

The lower-cost path fails the unchanged leave-one-league block-bootstrap gate. Profit concentration also remains high, so v8.19 is rejected rather than promoted as a more conservative calibration.

## v8.20 ten-yuan single-position stress

To test whether v8.18 depends on a few CNY 15 positions, the model, selections, 0.75 Kelly fraction and daily budget were frozen while the single-position cap was reduced to CNY 10.

| Cost | Bets | Staked | Profit | ROI | Block lower 95% | Leave-one-source minimum | Leave-one-league minimum | Max drawdown | Top-10 profit / net profit | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 118 | 334.24 | +108.03 | 32.32% | +16.44% | +2.41% | +2.04% | 22.29 | 92.8% | Survivor stress |
| 5.0% | 108 | 309.16 | +113.23 | 36.63% | +23.27% | +8.04% | +7.31% | 22.29 | 88.5% | Survivor stress |

The edge survives a lower single-position cap and becomes less concentrated, but aggregate profit and profit-to-drawdown are lower than v8.18 while maximum drawdown is unchanged. v8.20 is retained as robustness evidence only; v8.18 remains the thirteenth prospective paper challenger.

## v8.21 same-day league exposure cap

Team-level attribution found no persistent repeated-team concentration: no team appeared more than four times. The actionable portfolio dependency was same-day same-league exposure. There were 13-14 such historical groups, and one league-day reached CNY 27.92. v8.21 preserves every v8.18 signal, probability and initial Kelly stake, then proportionally scales all positions in a decision-day/league group when their combined frozen stake exceeds CNY 15. It does not remove positions by result and does not reallocate released capacity after settlement.

| Cost | Bets | Positive months | Staked | Profit | ROI | IID lower 95% | Block lower 95% | Leave-one-source minimum | Leave-one-league minimum | Max daily league stake | Max drawdown | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 118 | 16 / 24 | 339.38 | +118.76 | 34.99% | +10.49% | +19.04% | +5.47% | +2.57% | 15.00 | 22.29 | Survivor |
| 5.0% | 108 | 17 / 24 | 314.30 | +123.96 | 39.44% | +14.81% | +25.96% | +12.45% | +8.04% | 15.00 | 22.29 | Survivor |

Compared with v8.18, the 5% path raises profit from CNY 119.44 to CNY 123.96, increases positive months from 16 to 17, and raises the moving-block lower bound from +21.39% to +25.96%, while reducing stake. Both cost paths improve, so v8.21 is registered as a fourteenth paper-only policy. It remains unable to place real orders.

### v8.21 May replay

The fixed May selections occur on different dates, so the league-day cap does not alter them. The immutable replay remains two bets, CNY 8.13 staked and CNY 7.17 profit, with directions and stakes frozen before either result is attached. The two-bet month remains process evidence only.

### v8.21 temporal attribution correction

The cap changed only seven positions across three 2022 league-days. It reduced stake by CNY 19.27 and improved aggregate profit by CNY 4.52 on those dates; it made no change in the later segment beginning August 2023. v8.21 remains a defensible prospective portfolio constraint and passes the full historical gates, but its incremental historical profit is early-period attribution rather than independent late-period confirmation. It must not be described as a proven forward profit improvement until new capped league-days settle prospectively.

## v8.22 validation-reliability risk scaling

v8.22 kept the unshrunk v8.18 market-calibrated probability but multiplied each stake by the smaller of the two component calibration-reliability weights estimated solely from the prior three-month validation window. It also retained the v8.21 CNY 15 league-day cap.

| Cost | Bets | Active months | Staked | Profit | ROI | IID lower 95% | Block lower 95% | Leave-one-source minimum | Leave-one-league minimum | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 54 | 13 | 179.28 | +39.67 | 22.13% | -13.79% | -18.50% | -80.54% | -52.12% | Reject |
| 5.0% | 47 | 13 | 177.31 | +46.95 | 26.48% | -8.44% | -3.54% | -65.63% | -44.52% | Reject |

Reliability scaling removed too many small positions and made the surviving portfolio sparse and source/league dependent. No arbitrary weight floor was added after seeing this result. v8.22 is rejected.

### v8.22 May replay

The same two pre-result selections survive with a shared prior-only reliability multiplier of 0.955357. Stakes become CNY 1.73 and CNY 6.04; the first loses CNY 1.73 and the second earns CNY 8.58, ending May at CNY 6.85 profit on CNY 7.77 staked. This is lower than v8.21 and does not override the full-history rejection.

## Profit-concentration governance audit

The original survivor gates did not directly test whether net profit depended on a handful of favorable settlements. Three pre-specified diagnostics were therefore added without changing selections or using outcomes during stake construction: remove the five largest winning positions and require the three-month moving-block lower 95% ROI to remain positive; remove the ten largest winners and require retained aggregate profit to remain positive; and leave out every team with at least two exposures and require the worst moving-block lower bound to remain positive.

| Policy | Cost | Team lower 95% | Profit after top 5 removed | Top-5 block lower 95% | Profit after top 10 removed | New decision |
|---|---:|---:|---:|---:|---:|---|
| v8.18 | 2.5% | +9.64% | +47.80 | -8.61% | -0.93 | Reject |
| v8.18 | 5.0% | +13.92% | +53.00 | -3.19% | +4.27 | Reject |
| v8.21 | 2.5% | +12.94% | +53.24 | -22.71% | +6.43 | Reject |
| v8.21 | 5.0% | +18.08% | +58.44 | -15.95% | +11.63 | Reject |

The leave-one-team test passes in every path, so the failure is not attributable to a repeated team. All four paths fail the top-five moving-block gate. v8.18 also fails retained aggregate profit after ten winners are removed at 2.5% cost. v8.21 remains an immutable paper policy for prospective data collection, but its governance status is now `LEGACY_SURVIVOR_REJECTED_BY_NEW_CONCENTRATION_GATE`; it is not eligible for promotion.

## v8.23 equal-risk staking

One budget-neutral staking challenger was specified after the concentration audit. It preserves v8.21 eligibility using the original 0.75 Kelly minimum CNY 0.10 stake gate, then assigns CNY 3 to each eligible signal, or CNY 1.50 at minimum reference depth. The CNY 3 amount approximates v8.18's historical mean stake and was not selected from a profit grid. The CNY 15 same-day league cap and CNY 100 daily budget remain active.

| Cost | Bets | Staked | Profit | ROI | Positive months | IID lower 95% | Block lower 95% | Source lower 95% | League lower 95% | Top-5 block lower 95% | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 118 | 333.00 | +73.51 | 22.08% | 13 / 24 | -2.57% | -4.08% | -15.48% | -9.48% | -19.85% | Reject |
| 5.0% | 108 | 304.50 | +91.75 | 30.13% | 14 / 24 | +7.88% | +6.07% | -4.58% | -1.29% | -7.18% | Reject |

Equal risk removes useful stake ranking, fails the ordinary stability gates at 2.5% cost, and still fails the new concentration gate at both costs. It is rejected and is not registered as a runtime policy. In the fixed May 2026 replay, the two directions remain frozen before settlement; CNY 6.00 is staked and CNY 1.26 is earned. That two-event realization is process evidence only and does not alter the rejection.

The next model iteration should target probability and ranking quality with genuinely new temporally held-out evidence. Further transformations of these same 118/108 stakes are suspended because they cannot establish an independent edge and would increase researcher degrees of freedom.

## v8.24 regularized market-structure outcome probability

v8.24 tested one fixed probability-model upgrade rather than another stake transformation. The direct-CLV and probability-movement models, their intersection rules, the 25% conservative-probability gate, the 2% lower-CLV gate, quote-quality filters and league-day cap were unchanged. After each component selection was frozen, a `C=0.1` regularized logistic model estimated outcome probability from opening-only market-structure fields: consensus and conservative probability, execution and raw odds, dispersion, reference depth, cost, price ratio, nonlinear probability/odds terms, outcome, odds band, source type and their fixed interactions. It was trained on all broad candidates in the prior nine months. The immediate test month's result and closing price were absent from the prediction frame.

The frozen component counts match v8.18 exactly at 2.5% cost: 230 direct positions and 263 movement positions. The probability side channel therefore did not alter CLV component selection. On the trailing three-month inner validations, however, the logistic probability had worse mean Brier scores than the unmodified market probability: 0.190971 versus 0.188176 for the direct component and 0.193141 versus 0.188197 for the movement component.

| Cost | Bets | Staked | Profit | ROI | Positive months | IID lower 95% | Block lower 95% | Source lower 95% | League lower 95% | Max drawdown | Top-5 block lower 95% | Profit after top 10 removed | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 91 | 590.09 | +149.87 | 25.40% | 14 / 20 | +5.61% | +6.53% | -18.16% | -8.47% | 46.22 | -10.04% | -50.10 | Reject |
| 5.0% | 81 | 576.48 | +183.28 | 31.79% | 14 / 18 | +12.13% | +18.43% | -10.67% | -1.58% | 46.22 | -5.97% | -8.60 | Reject |

The higher headline profit is not accepted as improvement. The model worsens probability calibration, has fewer than 100 bets, doubles historical drawdown relative to v8.21, fails leave-one-source and leave-one-league robustness, and loses money after its ten largest winners are removed. It is rejected and not registered as a runtime policy.

### v8.24 fixed May replay

The fixed May 2026 component candidate IDs exactly match the archived v8.18 component IDs. Four positions receive a positive final Kelly stake under the new probability model. Directions and stakes are frozen before settlement.

| Date | Match | Direction | Odds | Stake | Daily profit | Month cumulative |
|---|---|---|---:|---:|---:|---:|
| 2026-05-09 | Kocaelispor vs Karagumruk | Away | 4.038 | 2.05 | +6.23 | +6.23 |
| 2026-05-10 | Volos NFC vs Levadeiakos | Home | 2.813 | 2.72 | -2.72 | +3.51 |
| 2026-05-17 | Kasimpasa vs Galatasaray | Home | 4.038 | 4.15 | +12.61 | +16.12 |
| 2026-05-17 | Trabzonspor vs Genclerbirligi | Away | 2.421 | 10.85 | +15.42 | +31.54 |

The month stakes CNY 19.77 and earns CNY 31.54, while never exceeding the CNY 100 daily budget or CNY 15 league-day cap. This favorable month does not override the full-history rejection. It illustrates why month-level profit must remain a process demonstration rather than the model-selection objective.

## v8.25 validation-gated market residual

v8.25 keeps the market consensus probability as the center and permits the v8.24 logistic model to contribute only a validation-proven residual. In each fold, the residual weight is solved on the prior three-month validation window by minimizing Brier score, clipped to `[0, 1]`, shrunk by `n / (n + 50)`, and enabled only when the shrunk blend improves validation Brier by at least 0.001. Otherwise it deterministically falls back to the raw market probability. The immediate test month is never used to estimate the weight.

No direct-model fold among 30 evaluable folds and no movement-model fold among 31 evaluable folds met the improvement requirement. Every residual weight was therefore zero. This is useful negative evidence: the available opening market-structure fields do not support a reliable outcome-probability correction beyond consensus.

| Cost | Bets | Staked | Profit | ROI | Positive months | IID lower 95% | Block lower 95% | Source lower 95% | League lower 95% | Team lower 95% | Max drawdown | Top-5 block lower 95% | Profit after top 10 removed | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 133 | 350.34 | +99.44 | 28.38% | 14 / 24 | +5.37% | +10.12% | -2.72% | +3.03% | +4.73% | 17.41 | -4.58% | +7.70 | Reject |
| 5.0% | 126 | 332.19 | +117.11 | 35.25% | 15 / 24 | +12.69% | +20.63% | +9.69% | +12.51% | +15.11% | 17.41 | +4.79% | +25.37 | Survivor at stress cost only |

The 5% path passes every current gate, but the lower-cost path fails month stability, leave-one-source robustness and the top-five deletion gate. Dual-cost acceptance is required, so v8.25 is rejected and not registered.

### v8.25 fixed May replay

Four decisions receive positive market-centered Kelly stakes. The daily cumulative path is CNY `+2.10`, `+1.11`, then `+8.93`; total stake is CNY 5.77 and profit is CNY 8.93. All decisions and stakes are frozen before settlement. This favorable month is reported only as a process audit.

## v8.26 dual-cost-stable eligibility

The 5% v8.25 path suggested a cost-stability filter. v8.26 requires a candidate to receive a frozen positive stake under both 2.5% and 5% execution-cost assumptions, then sizes and settles the retained candidate using the 2.5% path. The 5% eligibility artifact contains only candidate ID and selected outcome; no result, profit or closing-price column is read by the 2.5% replay. Both fields must match, so a direction change under stress is rejected.

| Cost path | Bets | Staked | Profit | ROI | Positive months | IID lower 95% | Block lower 95% | Source lower 95% | League lower 95% | Team lower 95% | Max drawdown | Top-5 block lower 95% | Profit after top 10 removed | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% dual-cost intersection | 111 | 309.81 | +105.94 | 34.20% | 13 / 22 | +9.97% | +17.78% | +0.44% | +7.37% | +12.09% | 17.41 | -0.46% | +14.20 | Reject |
| 5.0% eligibility path | 126 | 332.19 | +117.11 | 35.25% | 15 / 24 | +12.69% | +20.63% | +9.69% | +12.51% | +15.11% | 17.41 | +4.79% | +25.37 | Survivor at this cost |

The intersection repairs source and league robustness and retains positive profit after deleting ten winners. It still has only 13 positive months out of 22 active months, or 59.09%, below the frozen 60% gate, and its top-five moving-block lower bound remains negative at -0.46%. Neither threshold is relaxed after inspection. v8.26 is rejected and not registered.

### v8.26 fixed May replay

The cost-stable intersection retains only Kocaelispor versus Karagumruk away at odds 4.038 on May 9. It stakes CNY 0.69 and earns CNY 2.10. Adding this already inspected favorable month causes the expanded historical summary to cross the current gates; that is not independent confirmation and cannot reverse the pre-May rejection. A future untouched month or prospective T-1 settlement is required for new evidence.

## v8.27 closing-probability-calibrated concentration governance

The absolute winner-deletion gate introduced after v8.22 was audited for statistical power before further signal filtering. The v8.26 positions were held fixed and 2,000 independent outcome paths were generated from each position's closing fair probability. Every simulated path used the original odds and stake, removed the same five and ten largest realized winners, and ran 1,000 three-month moving-block bootstrap samples. Simulated outcomes were used only for post-settlement gate diagnostics and never changed eligibility, direction, probability or stake.

The fixed v8.26 portfolio has CNY 22.71 expected profit and 7.33% expected ROI when valued at closing probabilities. Despite that positive benchmark edge, only 1.3% of simulated paths passed the old joint winner-deletion gate. The old rule therefore has an estimated 98.7% false-rejection rate under this benchmark and is not an appropriate hard gate for a 111-position portfolio.

v8.27 replaces only those two absolute thresholds with a pre-specified calibrated test. Observed top-five block lower ROI, top-ten retained profit and positive-active-month count must each be at or above the fifth percentile of their closing-probability simulation distributions. Ordinary aggregate profit, IID and moving-block lower bounds, sample size, active months, leave-one-source, leave-one-league, leave-one-outcome, leave-one-odds-band and leave-one-team gates remain unchanged. The v8.26 signals and stakes are unchanged.

| Cost | Bets | Staked | Profit | ROI | Positive months | IID lower 95% | Block lower 95% | Source lower 95% | League lower 95% | Team lower 95% | Max drawdown | Top-5 percentile | Top-10 percentile | Positive-month percentile | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 111 | 309.81 | +105.94 | 34.20% | 13 / 22 | +9.97% | +17.78% | +0.44% | +7.37% | +12.09% | 17.41 | 98.60% | 96.70% | 91.80% | Research survivor |
| 5.0% | 126 | 332.19 | +117.11 | 35.25% | 15 / 24 | +12.69% | +20.63% | +9.69% | +12.51% | +15.11% | 17.41 | 99.50% | 97.95% | 93.05% | Research survivor |

Both cost paths pass the calibrated and unchanged gates. v8.27 is the strongest current research candidate. The gate methodology was corrected after inspecting v8.26, so these historical folds cannot provide independent promotion evidence. It is registered only as a fifteenth immutable prospective shadow policy: runtime capture recomputes both 2.5% and 5% cost views, requires the same selected outcome and positive minimum stake, uses opening market consensus for Kelly sizing, caps daily exposure at CNY 100 and same-day league exposure at CNY 15, and never creates real orders. Fresh T-1 decisions must settle before any promotion decision.

### v8.27 fixed May replay

The directions and stakes are identical to v8.26. The fixed month contains one May 9 away position at odds 4.038, stakes CNY 0.69 and earns CNY 2.10. The daily limit remains CNY 100 and no same-day league exposure exceeds CNY 15. Because May was inspected before v8.27 governance was finalized, it remains a process demonstration rather than confirmation evidence.

## v8.28 restored independent-cost signal with calibrated governance

An attribution audit compared realized profit with profit valued at each position's closing fair probability. The v8.27 dual-cost intersection earned CNY 105.94 historically, but its closing-probability expected profit was only CNY 22.71 (7.33% ROI), with 3.40% expected ROI in the later segment beginning August 2023. The earlier v8.21 signal set had CNY 26.38 closing-probability expected profit (7.77% ROI) and 5.34% later-segment expected ROI. The dual-cost intersection therefore reduced sample coverage and expected CLV value; its better legacy concentration result came from a gate subsequently shown to have a 98.7% false-rejection rate under the positive closing-probability benchmark.

v8.28 restores the independently evaluated v8.21 signal and training-market-calibrated Kelly path. It does not inspect outcomes to restore positions. Each cost replay is still frozen month by month, uses only opening information for selection and staking, keeps the CNY 100 daily budget and CNY 15 same-day league cap, and attaches results only for settlement. The only governance change is applying the already specified closing-probability-calibrated concentration test to the unchanged v8.21 portfolios.

| Cost | Bets | Staked | Realized profit | Realized ROI | Closing expected profit | Closing expected ROI | Positive months | IID lower 95% | Block lower 95% | Source lower 95% | League lower 95% | Max drawdown | Top-5 percentile | Top-10 percentile | Positive-month percentile | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 118 | 339.38 | +118.76 | 34.99% | +26.38 | 7.77% | 16 / 24 | +10.49% | +19.04% | +5.47% | +2.57% | 22.29 | 93.60% | 96.50% | 97.65% | Research survivor |
| 5.0% | 108 | 314.30 | +123.96 | 39.44% | +24.69 | 7.86% | 17 / 24 | +14.81% | +25.96% | +12.45% | +8.04% | 22.29 | 96.75% | 98.25% | 99.55% | Research survivor |

The large gap between realized ROI and closing-probability expected ROI means the historical outcome profit contains substantial favorable variance. v8.28 is preferred to v8.27 because it improves the outcome-independent CLV benchmark, later-period expected value and coverage, not because it found a more profitable calendar month. It becomes the sixteenth immutable prospective paper policy and cannot create real orders.

### v8.28 fixed May replay

The fixed May process replay is the unchanged v8.21 month: two decisions, CNY 8.13 staked and CNY 7.17 realized profit. All directions and stakes are frozen before results are attached, 29 calendar days place no bet, and unused daily capacity is retained rather than reallocated after settlement. This inspected two-bet month is an anti-leakage demonstration only and is explicitly excluded from the evidence used to claim future profitability.

## v8.29 probability and coverage probes

The next iteration tested three pre-result changes against v8.28. A prior-only Ridge calibrator used strictly earlier settled positions to map predicted lower CLV, opening market gap, odds, dispersion and reference depth to closing edge. With only 118 selected observations, its 2.5% closing expected profit fell from CNY 26.38 to CNY 18.09 and later expected ROI fell from 5.34% to 3.89%; the probe was rejected. Raw opening consensus, lower-CLV probability and their minimum were also tested as Kelly inputs, but all produced lower closing expected profit than the existing training-market-calibrated probability.

Lowering the CLV admission threshold from 2% to 1% raised 2.5% closing expected profit to CNY 27.68, but maximum drawdown increased to CNY 26.08 and the leave-one-source moving-block lower bound became -0.0065%. Giving the 1%-2% tier half stake repaired all historical gates and produced CNY 27.03 closing expected profit, but maximum drawdown still increased to CNY 23.36 and expected-profit-to-drawdown declined from 1.184 to 1.157. The incremental expected profit of CNY 0.65 over 48 folds does not justify a new runtime policy. Single-model high-confidence satellite signals added only CNY 0.31/0.19 closing expected profit at 2.5%/5% cost and were also rejected as operationally immaterial.

No v8.29 policy is registered. These probes were evaluated across the fixed rolling calendar and both cost assumptions; no month was selected or removed because of its result.

## Closing-value profitability gate

Every agreement replay now reports outcome-independent profit attribution using each frozen position's closing fair probability. The gate records all-period and post-2023-08 closing expected profit, expected ROI, positive-CLV rate, and realized profit minus closing expected profit. A candidate is rejected when aggregate closing expected profit is non-positive or later-period closing expected ROI is non-positive. Closing prices remain settlement-only fields and can never change historical or runtime eligibility, direction or stake.

For v8.28, the 2.5% path has CNY 26.3827 closing expected profit, 7.7738% closing expected ROI and 5.3372% later-period expected ROI. Its realized CNY 118.76 profit exceeds closing expectation by CNY 92.3773. The 5% path has CNY 24.6911 closing expected profit, 7.8559% expected ROI and 4.5499% later-period expected ROI; realized profit exceeds closing expectation by CNY 99.2689. These large gaps are treated as favorable outcome variance, not as model edge.

## v8.30 to v8.32 rejected model probes

v8.30 admitted only the top quartile of prior-validation residual weights. No direct-model position qualified under either execution cost, while the movement path produced five losing positions. v8.31 replaced Ridge with a fixed Extra Trees research estimator; at 2.5% cost it produced 118 positions, CNY 17.01 closing expected profit and 4.30% later expected ROI, but failed the established robustness gates. v8.32 shortened training and validation to 6 and 2 months; its 108 positions produced CNY 15.95 closing expected profit, again below v8.28, and failed the same gates. None is registered for runtime use.

## v8.33 non-overlapping multi-horizon core and satellite

v8.33 keeps the unchanged v8.28 9m/3m signal as its core. An independently frozen 18m/9m agreement model may contribute a position only when the core rejects the same opening candidate. It never replaces an eligible core position, never changes direction after settlement, and receives half of its original 0.625 Kelly sizing, or an effective 0.3125 Kelly. The combined portfolio is capped jointly at CNY 100 per day and CNY 15 per league-day.

| Cost | Positions | Core / satellite | Staked | Realized profit | Closing expected profit | Closing expected ROI | Later expected ROI | Block lower 95% | Source lower 95% | League lower 95% | Team lower 95% | Max drawdown | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 182 | 118 / 64 | 368.98 | +128.22 | +28.89 | 7.83% | 5.85% | +19.50% | +12.14% | +6.21% | +14.03% | 22.29 | Research survivor |
| 5.0% | 168 | 108 / 60 | 353.01 | +134.89 | +26.68 | 7.56% | 4.11% | +25.87% | +18.31% | +12.43% | +19.47% | 22.29 | Research survivor |

Both cost paths retain positive closing expected value in the later period and pass IID, moving-block, source, league, team and calibrated concentration gates. The improvement over v8.28 is CNY 2.50 closing expected profit at 2.5% cost while preserving maximum drawdown. v8.33 is therefore registered as the seventeenth immutable prospective shadow policy. It remains paper-only and requires fresh T-1 settlements before any promotion.

### v8.33 fixed May replay

The pre-settlement May process contains four positions. May 9 stakes CNY 0.35 on Karagumruk away and closes at +1.06 cumulative. May 10 stakes CNY 1.81 on Volos home and moves cumulative profit to -0.75. On May 17, CNY 6.32 on Genclerbirligi away and CNY 0.35 on Kasimpasa home settle the month at +9.29. All other May days retain cash. This month demonstrates decision-time freezing and settlement timing only; it is not model-selection evidence.

## v8.34 non-overlapping three-horizon sequence

The next pre-specified horizon was trained on 12 months and validated on the immediately following 6 months. Used alone, it is not robust enough: the 2.5% replay contains 80 positions and the 5% replay contains 74, both below the 100-position gate. Their monthly and moving-block lower confidence bounds are negative, and their leave-one-source, leave-one-league and leave-one-team checks also fail. The standalone 12m/6m model is therefore rejected under both execution-cost assumptions.

v8.34 keeps every v8.33 position unchanged and tests the 12m/6m model only on candidates rejected by both earlier horizons. The fixed order is 9m/3m core, 18m/9m satellite, then 12m/6m tertiary. The two supplemental horizons use effective 0.3125 Kelly, share the same CNY 100 daily budget and CNY 15 league-day cap, and cannot duplicate or replace an earlier eligible position.

| Cost | Positions | 9m3m / 18m9m / 12m6m | Staked | Realized profit | Realized ROI | Closing expected profit | Closing expected ROI | Later expected profit | Later expected ROI | Block lower 95% | Source lower 95% | League lower 95% | Team lower 95% | Max drawdown | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 193 | 118 / 64 / 11 | 373.98 | +129.04 | 34.50% | +29.1369 | 7.7910% | +5.3990 | 5.7805% | +19.5696% | +12.3565% | +6.2797% | +14.2165% | 22.29 | Research survivor |
| 5.0% | 181 | 108 / 60 / 13 | 359.28 | +136.01 | 37.86% | +27.0691 | 7.5343% | +3.3312 | 4.2327% | +25.6345% | +18.5069% | +12.6119% | +19.2779% | 22.29 | Research survivor |

Against v8.33, v8.34 adds only 11 and 13 non-overlapping positions. Closing-probability expected profit improves by CNY 0.2506 at 2.5% cost and CNY 0.3856 at 5% cost, while maximum drawdown remains CNY 22.29. This is a modest coverage gain rather than evidence of a large new edge. No calendar month was selected, removed or reweighted because of its outcome; all 48 rolling folds remain in both comparisons.

v8.34 is registered as the eighteenth immutable prospective shadow policy. Its runtime models, hashes, training window and sequential role are frozen. It cannot create real orders, and historical survival does not permit promotion. Fresh T-1 decisions, immutable price snapshots and later-observed settlements are required to measure prospective CLV and realized performance.

### v8.35 runtime replay parity correction

A configuration audit found that the v8.33 and v8.34 runtime supplemental horizons used a minimum staking probability of 0.0, while every formal 18m/9m and 12m/6m historical agreement replay required 0.25. The core already used 0.25. Allowing the runtime satellites below the replay threshold would expose the paper portfolio to candidates that never passed the historical evaluation.

The registered v8.34 policy remains immutable. v8.35 creates a nineteenth immutable paper policy with the same models, fixed horizon order, thresholds, Kelly fractions and exposure caps, except that both supplemental minimum staking probabilities are corrected to 0.25. This exactly matches the historical v8.34 replay population: 193 positions at 2.5% cost and 181 at 5% cost. It is a runtime parity correction, not a result-selected signal change, and it cannot create real orders.

The replay output now includes `horizon_role_attribution`. For v8.34 at 2.5% cost, the 9m/3m core contributes CNY 26.3827 closing expected profit from 118 positions, the 18m/9m satellite contributes CNY 2.5036 from 64, and the 12m/6m tertiary contributes CNY 0.2507 from 11. At 5% cost the corresponding values are CNY 24.6911, CNY 1.9925 and CNY 0.3856. The tertiary role is labelled `COLLECTING`, not validated, because both paths remain below 30 observations.

Runtime collection now has a dedicated immutable closing-evidence chain. During the final 15 minutes before kickoff, the authorized external feed is captured at most once per match. For each frozen candidate, the execution bookmaker is excluded, each remaining bookmaker is de-vigged, and the normalized component median becomes the closing reference probability. The stored CLV is `execution_odds * closing_reference_probability - 1`. Closing evidence is observed only after the decision and before kickoff, cannot update the direction or stake, and cannot be updated or deleted from the database.

### v8.35 fixed May calendar ledger

The complete May 2026 ledger contains 31 rows, including 28 no-bet days. Four positions are frozen before settlement. May 9 stakes CNY 0.35 on Karagumruk away and ends at CNY +1.06. May 10 stakes CNY 1.81 on Volos home and ends at CNY -0.75. May 17 stakes CNY 0.35 on Kasimpasa home and CNY 6.32 on Genclerbirligi away; the month ends at CNY +9.29. Total stake is CNY 8.83, realized ROI is 105.21%, maximum daily stake is CNY 6.67, maximum league-day stake is CNY 6.67 and maximum drawdown is CNY 1.81. Every daily and league cap is respected.

The four positions have closing-probability expected profit of CNY -0.6151. Two winning positions also have negative CLV, including the largest CNY 6.32 position. The favorable CNY +9.29 realized result therefore does not demonstrate a profitable algorithm; it is consistent with favorable result variance in a tiny sample. The month is retained as an anti-leakage and accounting audit and is forbidden from selecting v8.36 parameters.

### Outcome-independent monthly governance

Portfolio governance now builds a second monthly ledger from each frozen position's closing fair probability. Its monthly profit is `stake * (closing_probability * execution_odds - 1)`; the match result is never read. Both an IID monthly bootstrap and a three-month moving-block bootstrap must have a positive 95% lower bound. Changing every historical winner to a loser leaves this diagnostic unchanged.

The unchanged v8.34 replay remains a research survivor under this stronger gate. At 2.5% cost, 38 of 40 active months have positive closing expected profit; the IID lower bound is +5.1485% and the moving-block lower bound is +5.7231%. At 5% cost, 34 of 38 active months are positive; the corresponding bounds are +4.6801% and +5.0004%. These values are materially below the 34.50% and 37.86% realized ROIs and are therefore the primary profitability benchmark. Realized results remain useful for settlement and drawdown accounting but cannot promote an algorithm.

### Rejected low-confidence coverage challenger

An exploratory challenger preserved every v8.35 position and then appended non-overlapping candidates with a 1%-2% predicted lower CLV at one quarter of the normal risk. Selection removed closing prices and match outcomes before filtering. A reusable challenger gate required both cost paths to improve closing expected profit by at least 2%, add at least 30 positions, retain non-decreasing later-period closing expected profit, keep closing-value bootstrap bounds positive and limit maximum drawdown growth to 5%.

At 2.5% cost, the challenger increased positions from 193 to 202 and closing expected profit from CNY 29.1369 to CNY 29.3472, a gain of only CNY 0.2103 or 0.7218%. At 5% cost, positions increased from 181 to 189 and expected profit from CNY 27.0691 to CNY 27.1733, only CNY 0.1042 or 0.3849%; later-period expected profit declined from CNY 3.3312 to CNY 3.3274. Maximum drawdown rose from CNY 22.29 to CNY 22.83. Both paths fail the materiality and minimum incremental sample gates, so no v8.36 runtime policy is registered. The experiment increases historical activity too little to justify extra live complexity.

### Rejected lower-probability supplemental coverage

A second coverage probe kept the 2% lower-CLV threshold but lowered the supplemental-horizon staking-probability floor from 0.25 to 0.20. Existing v8.35 positions retained priority; only non-overlapping 20%-25% candidates were appended at one quarter of normal supplemental risk. This produced 28 incremental positions at 2.5% cost and 30 at 5% cost without increasing maximum drawdown.

The added coverage did not add true value. At 2.5% cost, closing expected profit moved from CNY 29.1369 to CNY 29.1395, only +CNY 0.0026 or +0.0089%. At 5% cost it fell from CNY 27.0691 to CNY 26.8896, and later-period expected profit fell from CNY 3.3312 to CNY 3.1677. Intersecting the two cost-specific candidate sets still left negative 5% closing expectation. The lower probability floor is therefore rejected rather than used to manufacture more bets.

### Rejected heteroskedastic uncertainty probes

The direct CLV model originally used a common validation RMSE for every execution price. A two-sided heteroskedastic probe multiplied that RMSE by `clip(sqrt(odds / 3), 0.75, 1.5)`. It incorrectly relaxed short-priced candidates while penalizing long prices. At 2.5% cost its closing expected profit fell by CNY 2.7147 and maximum drawdown increased 11.98%; at 5% cost expected profit fell by CNY 1.5203. It was rejected.

A one-way version changed the lower clip to 1.0, but rerunning it against the old v8.34 artifacts exposed code-version drift: a stricter rule appeared to add positions because the current replay pipeline and historical frozen artifacts were not generated by the same code contract. A current-code `rmse_grid` parity control was therefore generated before any conclusion was accepted. Against that matched control, changing uncertainty during inner model selection improved closing expected profit by only 0.85% and 0.54%, below the 2% materiality threshold.

The final freeze-only probe held training, inner validation and hyperparameter selection identical to the current-code parity control and applied one-way odds scaling only when freezing the test-month decision. Each direct-model candidate set was verified as a subset of its parity control, with zero added candidates. After model agreement and sequential horizon fallback, the final portfolio counts were unchanged. Closing expected profit declined by CNY 0.0696 at 2.5% cost and CNY 0.0252 at 5% cost. This interpretable version is also rejected. No heteroskedastic runtime policy is registered.

### Rejected direct lower-quantile models

The next model-level probe replaced `mean prediction - RMSE margin` with a direct conditional quantile estimate of closing edge. Quantile regression used only opening market-structure fields, a fixed regularization strength and no match-result features. It was research-only and could not be exported to runtime. A q=0.25 model produced zero positions across the 48 core folds. A less conservative q=0.40 model produced only two positions in one active month, both draws; it failed the minimum sample, active-month and outcome-concentration gates.

A Ridge residual-quantile alternative retained the mean model and derived its lower bound from the inner validation residual's 25th percentile. It also produced zero core positions at 5% execution cost. The agreement and three-horizon stages were therefore not run. Direct 25th- or 40th-percentile closing-edge estimation is too conservative for the current rolling sample and cannot solve low portfolio utilization. No quantile policy is registered.

### Rejected positive-CLV probability gate

A two-stage challenger separated predicted CLV magnitude from the probability that CLV would finish above zero. For each 9m/3m fold, a logistic classifier was trained only on earlier opening market-structure fields with `closing_edge_pct > 0` as its label. The test month contained no closing prices or results. Fixed probability thresholds of 0.50, 0.55 and 0.60 were evaluated as an exploratory sensitivity band; realized match profit was excluded from challenger selection, and the classifier cannot be exported to runtime.

| Gate | Agreement positions | Closing expected profit | Closing expected ROI | Later expected profit | IID lower 95% | Block lower 95% | Max drawdown |
|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 123 | 23.1284 | 7.5896% | 2.6619 | 4.5448% | 5.0301% | 22.00 |
| 0.50 | 122 | 22.7575 | 7.5291% | 2.1743 | 4.4253% | 4.8476% | 22.00 |
| 0.55 | 120 | 17.5170 | 6.2088% | 2.0754 | 3.2210% | 1.9503% | 24.96 |
| 0.60 | 70 | 12.4557 | 7.4403% | 1.5024 | 4.9657% | 4.7168% | 24.96 |

The 0.60 model raised the direct selection's positive-CLV rate to 77.88%, but this binary accuracy improvement discarded too much stake-weighted CLV magnitude. Lowering the agreement threshold from 2% to 1% added only one position and changed closing expected profit to 12.4602. Even the least restrictive 0.50 gate reduced both total and later-period closing expected profit. All thresholds fail the outcome-independent challenger gate and no runtime policy is registered. The result shows that positive-CLV classification is not a substitute for optimizing calibrated, stake-weighted closing value.

### Positive-CLV probability stake reallocation

The same classifier was then evaluated as a sizing signal without deleting any baseline candidate. All 123 core agreement positions were preserved. Probability quartiles showed monotonic closing-value separation: their stake-weighted closing expected ROIs were 4.16%, 5.16%, 8.41% and 8.84%. A downweight-only rule did not improve absolute expected profit because even the lower quartiles remained positive. The staking engine was extended to support an explicitly bounded research uplift while retaining the CNY 15 single-position cap, CNY 15 league-day cap and CNY 100 daily cap.

At 5% execution cost, an uplift of up to 25% improved closing expected profit by 6.23% but increased maximum drawdown by 6.59%, above the 5% limit. Limits of 15% and 10% retained material expected-profit gains but also failed the drawdown gate. A maximum 5% uplift passed the core gate: closing expected profit rose from CNY 23.1284 to CNY 23.7959, or 2.8861%; later expected profit rose from CNY 2.6619 to CNY 2.7287; maximum drawdown rose only 3.6364%; and the IID and moving-block closing-value lower bounds remained positive.

The independent 2.5% path also improved closing expected profit, from CNY 23.3982 to CNY 24.0510, or 2.7900%, with the same 3.6364% drawdown increase. It nevertheless failed cross-cost governance because the leave-one-league moving-block lower bound moved from +0.1786% to -0.3506%. Selecting or excluding the offending league after observing this diagnostic would be outcome-driven overfitting, so the stake reallocation is retained only as a prospective research candidate. It is not registered for runtime use and the unchanged production paper policy remains authoritative.

### v8.55 cross-cost confidence uplift

v8.55 replaces each cost-specific sizing probability with the lower positive-CLV probability from independently trained 2.5% and 5% models for the same candidate and outcome. Missing peer candidates receive no uplift. Positions below the fixed 0.75 probability anchor keep their existing stake; positions above it may receive at most a 5% uplift. No position is deleted, and all original single-position, league-day and CNY 100 daily caps remain in force. The peer merge reads only candidate identity, direction and decision-time probability; future prices and results are ignored.

The core-only 2.5% path still had a marginally negative leave-one-league lower bound. The fixed rule was therefore applied unchanged to the pre-existing three-horizon sequence, whose supplemental horizons diversify the core without replacing it. Candidate counts and horizon roles exactly match the current-code parity control.

| Cost | Positions | Closing expected profit | Improvement | Later expected profit | IID lower 95% | Block lower 95% | Source lower 95% | League lower 95% | Team lower 95% | Max drawdown | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2.5% | 201 | 26.8786 | 2.6967% | 4.6875 | 4.9169% | 5.3633% | 9.4150% | 4.2438% | 11.8893% | 22.80 | Historical challenger accepted |
| 5.0% | 192 | 26.1753 | 2.7425% | 3.9843 | 4.6485% | 4.9330% | 17.7766% | 9.5236% | 16.1147% | 22.80 | Historical challenger accepted |

Against matched current-code baselines, maximum drawdown increases by 3.6364%, below the 5% limit, while both costs exceed the 2% material closing-profit threshold and retain positive later-period value. Historical acceptance does not permit runtime promotion. The logistic side models and cross-cost stake rule remain paper-only until they are serialized under an immutable model contract and pass fresh prospective T-1 evidence gates.

### v8.55 fixed April calendar ledger

The latest fully evaluated month in the frozen 48-fold archive is April 2026; May is excluded as the latest archived month and was not substituted based on profit. The conservative 5% v8.55 ledger contains all 30 calendar days, including 28 no-bet days. On April 4 it stakes CNY 1.67 on Kayserispor away and loses CNY 1.67. On April 6 it stakes CNY 1.94 on Bristol City home and wins CNY 4.28. The month ends at CNY +2.61 after CNY 3.61 total stake, with CNY 1.67 maximum drawdown and CNY 0.4811 closing-probability expected profit.

Neither April position qualifies for the cross-cost confidence uplift, so the month is identical to the matched baseline. Its 72.30% realized ROI is a two-position settlement outcome and cannot select or promote the algorithm. The complete daily ledger preserves zero-investment days, freezes directions and stakes before settlement, and respects both daily and league-day limits.

### v8.55 prospective shadow contract

Six immutable `positive_clv_logistic_v1` JSON artifacts cover the 9m/3m, 12m/6m and 18m/9m horizons under both 2.5% and 5% exchange-cost assumptions. Each artifact contains its exact training window, market-structure feature contract, standardized numeric and one-hot categorical coefficients, validation Brier score, parity error and SHA-256. Export-to-JSON parity errors are below `6e-16`; changing any coefficient without recomputing the policy artifact is rejected by the runtime hash check.

The paper runtime now registers `clv-ridge-v8.55-cross-cost-positive-clv-uplift-prospective-shadow` alongside the unchanged v8.35 policy. For a frozen selected horizon it independently reconstructs the 2.5% and 5% opening candidates. A direction mismatch, failed market gate or missing peer candidate leaves the multiplier at 1.0. Otherwise the two classifier probabilities are scored from JSON, the lower probability is divided by the fixed 0.75 anchor and the result is clipped to `[1.0, 1.05]`. The immutable decision stores the consensus probability, applied multiplier and six-artifact combined hash. Migration `0028_positive_clv_confidence_shadow.sql` adds those audit fields without mutating prior decisions.

At its initial deployment, the backend experiment endpoint reported 20 parallel paper policies and identified v8.55 as `HISTORICAL_CHALLENGER_ACCEPTED_PROSPECTIVE_REQUIRED`. It started with zero prospective settlements. Historical acceptance cannot promote it, and this policy path never creates real orders. The later v8.57 registration raises the parallel policy count to 21 while retaining v8.55 as the unchanged control.

### v8.56 low-CLV coverage probe

The next experiment lowered the decision-time lower-CLV threshold from 2% to 1% without changing models, costs, directions or the no-leakage contract. A temporal diagnostic used data through May 2024 as discovery and August 2024 onward as validation. The additional 1%-2% mid-horizon tier retained positive closing value in both segments; the core tier did not retain positive validation value and the long tier was negative in both segments. The fixed challenger therefore added only the mid-horizon tier at quarter risk after the existing tertiary multiplier.

The final portfolio added only three positions at 2.5% cost and four at 5% cost. Closing expected profit improved by only 0.0074% and 0.1131%, respectively, while several robustness margins weakened slightly. This is below the fixed 2% materiality threshold, so v8.56 is rejected and is not registered for prospective runtime use.

### v8.57 growth confidence uplift

Because the objective has unlimited principal but a fixed CNY 100 daily investment ceiling, v8.57 tests a growth mandate without manufacturing extra bets. It keeps the exact v8.55 selections, directions, models and exposure caps, but raises the maximum cross-cost positive-CLV confidence multiplier from 1.05 to 1.25. The lower probability from the independently frozen 2.5% and 5% classifiers remains authoritative. Missing peers, cost-direction mismatches and failed market gates still receive no uplift.

| Cost assumption | Positions | Closing expected profit | Improvement vs v8.55 | Later expected profit | IID lower 95% | Block lower 95% | Maximum drawdown | Drawdown increase | Gate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 2.5% | 201 | 27.7831 | 3.3651% | 4.7695 | 5.0024% | 5.4331% | 23.45 | 2.8509% | Accepted |
| 5.0% | 192 | 27.0646 | 3.3975% | 4.0510 | 4.7189% | 5.0016% | 23.45 | 2.8509% | Accepted |

Both outcome-independent challenger gates pass the fixed 2% expected-profit materiality rule and 5% relative drawdown-growth limit. Leave-one-source, leave-one-league and leave-one-team lower bounds remain positive under both costs. v8.57 is registered only as a parallel paper policy; v8.55 remains unchanged as its prospective control, and no historical result authorizes real-money promotion.

### v8.58 walk-forward adaptive confidence cap

The fixed 1.25 cap has positive incremental closing value in both an early discovery segment and the later August 2024-April 2026 validation segment, but the later gain is materially smaller. v8.58 therefore removes the full-sample cap choice from each monthly decision. Before a calendar month begins, it compares the already frozen v8.55 and v8.57 paper stakes for strictly earlier months. The 1.25 cap is enabled only after at least 10 prior uplifted positions and positive cumulative incremental closing expected profit; otherwise the cap remains 1.05. Current-month closing prices and all match outcomes are excluded.

The first historical growth-cap activation is April 2022, after 11 prior uplifted observations. At 2.5% cost the walk-forward portfolio retains all 201 positions, increases closing expected profit from 26.8786 to 27.5242 (+2.4019%), and leaves maximum drawdown unchanged at 22.80. At 5% cost it retains all 192 positions, increases closing expected profit from 26.1753 to 26.8057 (+2.4083%), and again leaves maximum drawdown at 22.80. Both outcome-independent challenger gates pass; later expected profit and all source, league and team robustness lower bounds remain positive.

Runtime v8.58 stores the selected monthly cap, prior uplifted-position count and prior closing expected-profit delta on every immutable decision. Migration `0029_adaptive_confidence_cap_audit.sql` adds these audit fields. The policy remains prospective paper-only and starts at the conservative 1.05 cap until genuinely new prior-month closing evidence satisfies the fixed rule.

The fixed April 2026 process audit remains two positions over 30 calendar days, CNY 3.61 staked, CNY 2.61 realized profit, CNY 1.67 maximum drawdown and CNY 0.4811 closing expected profit. This unchanged two-bet month is retained only to demonstrate daily accounting and cannot select v8.58.

### v8.59 decision-time odds-band tilt

The v8.58 audit shows that every direction and horizon role retains positive closing value in both discovery and validation periods, so no outcome or horizon is deleted. Odds 2.0-3.0 have higher closing expected ROI than odds 3.0-4.0 in both broad periods. A fixed no-result probe therefore moved 5% stake weight from the 3.0-4.0 band to the 2.0-3.0 band using frozen execution odds only, followed by the unchanged daily and league caps.

Aggregate closing expected profit improved by 2.3837% at 2.5% cost and 2.3611% at 5% cost, with maximum drawdown increasing by 3.1140%. The fixed challenger gate nevertheless rejected both paths because later-period expected profit fell from 4.7695 to 4.7404 and from 4.0510 to 3.9988. This indicates that the historical odds-band spread is weakening. v8.59 is rejected and is not registered for runtime use; a full-period gain cannot override a deteriorating later holdout.

The model archive contains 48 evaluated folds, but a complete natural-calendar audit must also include the empty months between them. Across all 56 calendar months from September 2021 through April 2026, v8.58 has 40 active months at 2.5% cost and 38 at 5% cost. Realized profitable-active-month rates are 65.00% and 73.68%, while closing-probability expected-positive-active-month rates are 95.00% and 92.11%. Total theoretical CNY 100 daily-cap utilization is only about 0.21%, confirming that candidate coverage, rather than the budget ceiling, is the main constraint on absolute profit.

### v8.60 cross-cost direct-only core tier

The low budget utilization motivated a coverage experiment rather than another stake increase. Candidates selected by the frozen direct core model but absent from the three-horizon agreement portfolio were joined across the independently trained 2.5% and 5% positive-CLV classifiers. Mid- and long-horizon direct-only candidates turned negative in the later validation segment and were rejected. Core direct-only candidates retained positive closing value in both discovery and validation at both costs.

The fixed tier requires the same candidate and direction under both costs, a minimum classifier consensus of 0.65, no match conflict with the existing v8.58 portfolio, and half-Kelly sizing from the frozen training-market probability. It adds 36 positions at 2.5% cost and 33 at 5% cost. Closing expected profit increases from 27.5242 to 28.5919 (+3.8791%) and from 26.8057 to 27.5199 (+2.6644%). Later expected profit rises to 5.3266 and 4.2546, respectively, while maximum drawdown remains 22.80. Both fixed challenger gates pass the 30-position coverage, 2% materiality, later-period, drawdown and robustness requirements.

Runtime v8.60 evaluates this tier only after the core, long and mid agreement horizons all reject. It requires a direct lower-CLV estimate of at least 1%, an available training-market staking probability and cross-cost positive-CLV consensus of at least 0.65. The tier uses fixed half Kelly and does not receive an additional confidence multiplier. It is registered as a parallel prospective paper policy; historical acceptance cannot authorize real-money use.

In the unchanged April 2026 process month, v8.60 adds one Peterborough-Port Vale away position to the two v8.58 positions. The three-position ledger stakes CNY 4.17 and realizes CNY +4.53 with CNY 1.67 maximum drawdown, but closing expected profit falls from CNY 0.4811 to CNY 0.3527. The added position happened to win despite negative closing attribution in that month. This is direct evidence that the 108.63% realized monthly ROI is settlement luck and must not be used to promote the tier; only the full rolling and fresh prospective evidence governs it.

An expanding monthly activation probe required at least 10 prior direct-only observations and positive cumulative incremental closing value. It retained only 25 incremental positions at 2.5% cost and 22 at 5% cost, below the fixed 30-position coverage requirement, and did not deliver a material cross-cost improvement. This adaptive activation variant is rejected. The fixed v8.60 paper tier is retained specifically to collect unbiased prospective evidence.

The runtime promotion gate now evaluates `9m3m_direct_only` independently from the base portfolio. v8.60 cannot pass until that role alone has at least 30 immutable closing observations, positive average closing edge and at least 50% positive CLV. Base-strategy settlements cannot satisfy these incremental-role requirements.

### v8.60 complete natural-month distribution

The complete audit contains all 1,703 calendar days from September 2021 through April 2026, including every zero-position day and 15/17 entirely empty months under 2.5%/5% costs. At 2.5% cost, 27 of 41 active months are profitable and 14 lose, a 65.85% profitable-active-month rate; an arbitrary calendar month is profitable 48.21% of the time, losing 25.00% and otherwise empty. At 5% cost, 29 of 39 active months are profitable and 10 lose, a 74.36% profitable-active-month rate; an arbitrary calendar month is profitable 51.79%, losing 17.86% and otherwise empty.

The median active-month realized profit is approximately CNY 1.00. The 10th-90th percentile active-month range is CNY -1.52 to +9.14 at 2.5% cost and CNY -1.01 to +9.87 at 5% cost. The best realized month is April 2022 at CNY +32.49, the worst is March 2022 at CNY -12.04, and the worst closing-expected month is March 2023 at CNY -0.8709. These extrema are diagnostics only and cannot select an algorithm. Full daily and monthly ledgers are stored under `reports/monthly_distribution_v8_60_*`.

### Direct-only calibration probes after v8.60

The direct-only tier contains only about 40 cross-cost candidates at the 0.65 threshold. Predicted positive-CLV probability and predicted lower CLV are not reliably monotonic inside this small subgroup: under 5% cost the validation subset with predicted lower CLV above 5% has negative observed closing value, while the 3%-5% subset remains positive. Fitting a dedicated classifier to this sample would be underpowered and is deferred until prospective evidence grows.

Lowering the classifier threshold to 0.50 expands the cross-cost diagnostic pool to 58-60 candidates and retains positive average closing value in both discovery and validation. Uniform half-Kelly sizing raises expected profit but increases maximum drawdown by more than the fixed 5% limit. Uniform three-eighths Kelly passes drawdown but is dominated by v8.60 on expected profit and risk.

A two-tier probe keeps half Kelly above 0.65 and assigns one-eighth, one-quarter or three-eighths Kelly to probabilities from 0.50 to 0.65. All variants add a small amount of expected profit, but the improvement over v8.60 is only approximately 0.2%-0.6%, below the fixed 2% materiality requirement, while risk rises with the lower tier. These variants are rejected and are not registered for runtime use.

### v8.36 pre-registered evidence gate

The next genuine parameter challenger may be specified only after the 12m/6m tertiary role has at least 30 immutable prospective closing observations. At strategy level, at least 80% of settled selections must have a post-decision, pre-kickoff closing observation and average prospective closing edge must be positive. Any eventual challenger must then improve closing-probability expected profit under both 2.5% and 5% execution costs without increasing maximum drawdown by more than 5%, while preserving positive moving-block, leave-one-source, leave-one-league and leave-one-team lower bounds. Realized outcome profit cannot select the rule.

## Prospective evidence input recovery

The official Sporttery browser path is technically operational, but the upstream page currently returns an explicit `HTTP 567 Restricted Access` response. The system records that failure and does not bypass the access control or relabel another feed as official SP.

An authorized external research universe now uses The Odds API event endpoint for configured E0, E1 and Brazil fixtures. These rows are labelled `external_market`, remain separate from the official pool, and are eligible only for market-research shadow capture. Result observations are immutable: a completed score first observed before the stored kickoff is rejected, conflicting observations are quarantined, and settlement time is the system observation time rather than a provider timestamp. After deployment on 2026-08-11, the database contained 52 external fixtures: 30 Brazil, 12 E1 and 10 E0. The latest free event refresh processed 42 active fixtures; 10 older fixtures had settled only after kickoff. The immutable evidence table contained 52 pending observations and 10 later settled observations, with zero premature settlements and zero quarantined conflicts. This restores prospective evidence collection but does not itself validate v8.34 profitability.

### v8.60 prospective scheduler audit

The 2026-08-11 runtime audit confirmed that the named-book research and closing-evidence tasks were running successfully, but all 20 earliest active fixtures were still outside the fixed T-120 to T-60 decision window. Consequently v8.60 correctly had zero decisions and zero closing observations. The first fixture was scheduled to enter the window at 2026-08-14T17:00:00Z (2026-08-15 01:00 Asia/Shanghai); creating a decision earlier would violate the frozen historical timing contract.

The experiment runner now aggregates a shared blocker across all parallel paper policies instead of repeating it once per policy. Scheduler records distinguish `awaiting_primary_horizon` from a failed task and include the decision window, affected match count and next eligible timestamp. The active database had 48 future external fixtures; the configured 20-match scan remains ordered by kickoff and already includes the next eligible fixtures. Raising the global agent limit would also expand news, weather and Qwen work, so it is deferred until evidence shows that more than 20 simultaneous near-horizon fixtures are being omitted.

### v8.61 discovery-selected budget deployment

The v8.60 portfolio uses only about 0.22% of the theoretical CNY 100 daily budget across all calendar days. Because every broad decision-time direction, odds band and horizon role retained positive closing attribution in both discovery and validation periods, the next experiment changed only stake deployment. It tested the fixed multiplier grid `1, 1.25, 1.5, 2, 3, 5, 10, 20` using matches through May 2024. After multiplication, the unchanged CNY 15 single-position and league-day caps and CNY 100 daily cap were reapplied. The largest multiplier with cross-cost discovery maximum drawdown no greater than CNY 100 was 10; the 20 multiplier failed at CNY 171.78. Matches from August 2024 onward did not select the multiplier.

At 2.5% cost, v8.61 retains the same 237 positions, raises closing expected profit from CNY 28.5919 to CNY 113.9265 (+298.46%), and has CNY 43.7129 positive validation-period closing expected profit. At 5% cost, the unchanged 225 positions rise from CNY 27.5199 to CNY 104.0127 (+277.95%), with CNY 33.7991 positive validation expected profit. Full maximum drawdown is CNY 90.27 at both costs; validation drawdown is CNY 47.60/CNY 38.04 and maximum active-day stake is CNY 33.00/CNY 53.40. All remain below CNY 100.

The earlier leave-one diagnostics used realized settlement profit and can reflect direction-specific historical luck. v8.61 therefore adds a separate outcome-independent leave-one diagnostic whose pseudo-profit is frozen stake multiplied by closing edge. Under both costs, moving-block lower bounds remain positive after leaving out each execution source, league, outcome, odds band or team; the minimum is 3.0568%. Whole-portfolio closing-expected IID and moving-block lower bounds are also positive. The strategy is registered as the 24th parallel paper policy. It preserves all v8.60 selections and directions, does not place real orders, and inherits the independent `9m3m_direct_only` prospective evidence gate.

The fixed April 2026 process audit contains 30 calendar days, three betting days and 27 no-bet days. It stakes CNY 35.60, realizes CNY +37.29, reaches CNY 15.00 maximum drawdown and has CNY +2.5533 closing expected profit. The 104.75% realized ROI is settlement luck and cannot select or promote v8.61; the fixed month exists only to demonstrate that directions and stakes are frozen before results and daily accounting does not reveal future outcomes.

### v8.63 prior-active-month adaptive deployment

A confidence-tier multiplier grid did not beat the uniform v8.61 multiplier in discovery, so classifier probabilities are not used as a stake ranking. The next challenger instead fixes each month's multiplier before the month starts. A 24-rule discovery grid combines 3/6/12 prior active months, 3/5/10/20 minimum positions and 15/20 growth multipliers. The objective is maximum minimum cross-cost closing expected profit subject to CNY 100 maximum discovery drawdown. The selected rule uses a base multiplier of 10 and changes to 20 only when the preceding three active portfolio months contain at least 20 positions in each cost path and both realized profit and closing expected profit are positive in both paths.

The selected rule activates the growth multiplier in 10 historical months. At 2.5% cost, closing expected profit rises from v8.61's CNY 113.9265 to CNY 116.6134 (+2.3585%); at 5% it rises from CNY 104.0127 to CNY 109.8154 (+5.5788%). Validation-period expected profit remains positive at CNY 44.1151/CNY 37.3172. Full maximum drawdown remains CNY 90.27, maximum active-day stake remains below CNY 100, and all outcome-independent closing-expected bootstrap and leave-one lower bounds remain positive.

v8.63 is not registered in the live paper experiment yet. Its historical month gate requires simultaneous state from the 2.5% and 5% counterfactual portfolios, while runtime currently persists only one actual policy path. Approximating that gate with a single path would violate replay parity. The challenger is therefore recorded as `HISTORICAL_STAKE_CHALLENGER_ACCEPTED_RUNTIME_PARITY_BLOCKED`; v8.61 remains the 24th active paper policy until dual-cost prospective state is persisted and tested.

### v8.64 matched cross-cost adaptive deployment

v8.64 resolves the v8.63 runtime-parity blocker by restricting monthly evidence to candidate ID and direction pairs present in both historical cost paths. There are 197 such matched positions. Deployment still covers the unchanged 237/225 v8.60 portfolios, but the 10-to-20 growth switch can use only the matched evidence subset. Months with no matched evidence retain the frozen base multiplier rather than disappearing from the deployment calendar.

The same 24-rule discovery grid again selects three prior active evidence months, at least 20 matched positions, a base multiplier of 10 and a growth multiplier of 20. At 2.5% cost, closing expected profit reaches CNY 122.7072, a 7.7073% improvement over v8.61; validation expected profit is CNY 50.2089. At 5% cost, closing expected profit reaches CNY 110.9568, a 6.6762% improvement; validation expected profit is CNY 38.4586. Full maximum drawdown remains CNY 90.27, active-day stake remains below CNY 100 and every outcome-independent robustness lower bound remains positive.

Runtime v8.64 uses v8.61 decisions whose cross-cost confidence field proves same-direction eligibility. Before a calendar month starts, it reconstructs 2.5% and 5% net execution odds from the immutable raw quote, rebuilds cost-specific capped base stakes, and requires both prior realized profit and prior closing expected profit to be positive. Migration `0030_adaptive_budget_deployment_audit.sql` stores the selected multiplier, evidence-month and matched-position counts, both expected and realized cost-path totals, and the state label on each immutable decision. Later results cannot retroactively change a past multiplier. v8.64 is the 25th parallel paper policy and still cannot create real orders.

The unchanged April 2026 process month uses the base multiplier because its prior matched-evidence gate is not active. It contains three positions across three betting days, stakes CNY 35.60, realizes CNY +37.29, has CNY 15.00 maximum drawdown and CNY +2.5533 closing expected profit. As with every fixed-month audit, realized ROI cannot select the algorithm.

### Post-v8.64 rejected deployment probes

An expanded growth-multiplier grid tested `15, 20, 25, 30, 40, 50` while retaining the frozen discovery endpoint and all v8.64 evidence rules. Discovery selected 50, but the 2.5% validation path reached CNY 107.85 maximum drawdown, above the fixed CNY 100 limit. The expanded grid is rejected as a whole. A lower multiplier was not selected after viewing validation because that would use the holdout to tune the rule.

A separately pre-specified coverage probe retained the v8.60 half-Kelly tier above 0.65 cross-cost positive-CLV probability and added candidates from 0.50 to 0.65 at one-eighth Kelly. Frozen v8.64 monthly multipliers were then applied. It added 14 positions at 2.5% cost and 15 at 5% cost, but closing expected profit improved by only 0.2418% and 0.0940%. Both are below the fixed 2% materiality requirement, so the coverage tier is rejected despite remaining inside the drawdown limit.

Finally, an outcome-independent deployment diagnostic removed the requirement that prior matched evidence also have positive realized profit. It selected exactly the same 13 growth months and reproduced every v8.64 portfolio metric under both cost assumptions. This confirms that the historical growth decisions are already determined by prior cross-cost closing-value evidence rather than settlement luck. Because it changes no decision or metric, it is an audit finding rather than a new policy version.

### v8.64 prospective collection readiness

The live scheduler audit on 2026-08-11 found 20 eligible future fixtures but none inside the immutable T-120 to T-60 decision window. The first fixture enters that window at `2026-08-14T17:00:00Z` (`2026-08-15 01:00` Asia/Shanghai). `named_book_gap_primary_horizon_capture` and `named_book_gap_closing_evidence` both completed successfully; zero current decisions therefore reflects the timing guardrail, not a failed worker. v8.64 remains paper-only and must collect genuinely prospective decisions, closing observations and settlements before any promotion decision.

### Post-v8.64 continuous and drawdown deployment probes

A prior-only continuous deployment rule replaced the binary 10/20 multiplier with a smooth function of the minimum cross-cost closing expected ROI over the preceding active evidence months. A 72-rule grid was selected only through May 2024. The chosen rule used three prior months, at least 20 matched positions, slope 2.0 and cap 30, but it reduced full closing expected profit by 1.9233% and 0.6883% relative to v8.64 and also reduced validation expected profit. It is dominated and rejected.

A realized-drawdown budget probe then allowed a higher target multiplier while scaling each day's positions from the drawdown known before that day. Same-day outcomes were unavailable when stakes were frozen. Although the 5% cost path improved by 5.8308%, the 2.5% path lost 11.3771% of v8.64 closing expected profit and exhausted the CNY 100 drawdown budget. The result demonstrates execution-cost path dependence and is rejected. Removing all cost-sensitive positions was also dominated, reducing closing expected profit by 10.3509% and 2.7453%.

### Market-shape feature probe

The existing portable Ridge sees only the selected direction's probability, quote and dispersion. A research-only `market_shape` contract now preserves the complete leave-one-book-out opening 1X2 consensus: home/draw/away probabilities, entropy, favorite identity and strength, home-away gap, maximum cross-direction dispersion and the best executable quote's advantage over the second-best quote. These fields are computed before closing prices and results are attached.

Using the unchanged 48 monthly folds, 9m/3m windows, inner positive-month gate, bookmaker contract and 2.5%/5% execution costs, the richer model increased coverage to 276/213 direct positions but reduced average closing edge from 4.6065%/4.8290% to 3.8325%/4.0874%. Total closing expected profit fell from CNY 2.8792 to CNY 2.8104 at 2.5% cost and from CNY 2.6765 to CNY 2.4490 at 5% cost. Both monthly bootstrap lower bounds remained negative. The feature implementation is retained for future genuinely new data, but this historical model is rejected and is not exported or registered as a runtime policy.

### v8.66-v8.67 execution microstructure probes

The opening archive now derives the execution bookmaker's normalized 1X2 shape, raw overround, selected-direction probability gap from leave-one-book-out consensus, mean absolute gap on the other directions and selection specificity. These fields distinguish a direction-specific high quote from a bookmaker whose whole board is lower-margin.

Putting the fields directly into Ridge reduced average closing edge to 3.5474%/3.4854%, with negative monthly bootstrap lower bounds. A fixed two-stage version retained the market-structure Ridge and used microstructure only in a positive-CLV logistic classifier at 0.50. It modestly increased absolute expected profit, but reduced expected ROI and later expected ROI under both costs; the cross-cost common incremental set had no later observations. Both probes are rejected and not registered.

### v8.68 all-outcomes CLV ranking

The previous pipeline selected one direction per match by opening market EV before Ridge scoring. v8.68 instead scores every opening-eligible home, draw and away direction, then freezes at most one direction per match by predicted lower CLV. Results and closing prices remain absent from the decision frame.

The standalone 48-fold path produced realized monthly bootstrap lower bounds of +2.4103% at 2.5% cost and +5.1020% at 5% cost. Average closing edge was 4.9216%/4.4303%; only the 5% path passed the standalone rolling gate because the 2.5% path had fewer than 60% profitable active months. One favorable cost path cannot authorize replacement.

A stricter incremental tier required both cost paths to select the same match and direction and excluded every match already present in either v8.60 base portfolio. It added 56 positions with isolated closing expected ROI of 2.6386%/2.4977% and positive later attribution, but only seven later observations. The combined portfolio improved closing expected profit by 0.8111%/0.7976%, below the fixed 2% materiality threshold, while maximum drawdown rose 1.0526%. All other robustness checks passed. Both formal challenger gates reject v8.68; the reproducible replay is retained for future independent evidence but is not registered at runtime.

### 2026-08-13 prospective audit

The five-minute primary and closing loops remained active. A `2026-08-13 22:15` next-window warning referred to a Sporttery fixture in the combined research universe; the first labelled external-market fixture remains Wolverhampton Wanderers-Blackburn Rovers at `2026-08-14T19:00:00Z`, entering T-120 at `2026-08-14T17:00:00Z`. It is inside the first 20 ordered research fixtures, so the scan limit does not omit it.

### v8.69-v8.71 rejected coverage and sizing probes

v8.69 replaced the direct closing-edge target with closing-probability movement while preserving the all-outcomes candidate process. It produced 253/242 positions and average CLV of 4.0247%/3.9840%, but the 2.5% bootstrap lower bound was -3.8133%. The four-way intersection with v8.68 contained only 26 incremental positions, below the fixed 30-position coverage gate. Both variants are rejected.

v8.70 applied a pre-specified quarter-Kelly interpretation to the v8.68 incremental tier. Expected profit improved by 2.0303% at 2.5% cost but only 1.9971% at 5% cost. The 5% path misses the unchanged 2% materiality gate, and the multiplier was not adjusted after seeing that result. v8.71 combined the same tier with adaptive deployment; expected profit increased, but maximum drawdown rose to CNY 110.49 and breached the CNY 100 limit. Neither policy is registered.

### v8.72 wide all-outcomes candidate universe

v8.72 changes the algorithm before model scoring rather than searching for a favorable month. Its opening-only candidate universe uses fixed bounds: minimum price ratio 0.90, minimum conservative EV -15%, minimum consensus probability 8% and maximum price ratio 1.20. The unchanged market-structure Ridge then scores all home/draw/away directions, requires a lower predicted CLV of at least 1%, caps execution odds at 5.0 and freezes at most one direction per match.

The standalone 48-fold replay produced 206 positions at 2.5% cost and 186 at 5% cost. Average closing edge was 6.0670%/6.0605%, positive-CLV rates were 73.79%/72.58%, and realized monthly bootstrap lower bounds were +3.9759%/+9.8954%. The common cross-cost direction set contained 167 positions. After excluding every match already selected by either v8.60 base path, 46 genuinely incremental positions remained: 23 away, 21 home and 2 draw. Their isolated closing expected ROI was 7.2215%/7.1476%, with positive later attribution under both costs.

### v8.73 incremental gate and v8.74 adaptive deployment

v8.73 adds those 46 positions only when the v8.60 sequence rejects the match and independently frozen 2.5% and 5% models select the same direction. It uses the original one-tenth Kelly rule. At 2.5% cost, positions rise from 237 to 283 and closing expected profit rises from CNY 28.5919 to CNY 29.4130 (+2.8718%). At 5% cost, positions rise from 225 to 271 and expected profit rises from CNY 27.5199 to CNY 28.3254 (+2.9270%). Later expected profit improves, maximum drawdown rises only 2.5877%, and IID and moving-block lower bounds remain positive. Both formal gates accept the historical challenger.

v8.74 applies the already frozen v8.64 monthly 10/20 deployment rule to the combined portfolio. Incremental positions cannot select their own multiplier; the only previously absent deployment month receives a multiplier from unchanged, strictly prior v8.60 matched evidence. The 2.5% path reaches CNY 129.8283 closing expected profit and CNY 55.1992 later expected profit. The 5% path reaches CNY 117.7982 and CNY 43.1691. Improvements over v8.64 are 5.8033%/6.1658%; maximum drawdown is CNY 93.06, a 3.0907% increase and below the fixed CNY 100 limit. Both formal gates accept v8.74 as the current historical research champion.

Historical acceptance does not establish real profitability. Runtime uses two immutable JSON models from the last training window that passed under both costs (`2025-07-01..2026-03-31`), requires direction agreement and records the conservative 5% execution view. The newer 5% window ending 2026-05-31 failed inner validation, so v8.74 is explicitly paper-only, starts with no prospective authority and never creates real orders. Fresh pre-kickoff decisions, closing observations and settlements must validate it before any promotion discussion.

### v8.75-v8.82 temporal and objective diversification

An independently specified 18m/6m slow model removed the latest-window abstention but failed its standalone monthly bootstrap under both costs. Requiring fast and slow models to agree left only 11 incremental positions. Using the slow model only when the fast path abstained for an entire month added six positions beyond v8.73 and improved expected profit by less than 1%; using it as a general supplement was worse. These temporal variants are rejected.

Requiring positive risk-adjusted settlement profit inside the already trailing inner validation produced a stable 5% path but a negative 2.5% bootstrap lower bound. Its 33 cross-cost incremental positions did not outperform v8.74. Supplementing the CLV model with profit-gated, probability-movement or narrow-universe model selections increased position counts but reduced expected profit. The evidence rejects model unions as a coverage shortcut: additional directions need positive marginal closing value, not merely a different training target.

### v8.83-v8.91 market structure and microstructure

The wide all-outcomes market-shape model added full 1X2 entropy, favorite strength, home-away gap and cross-direction dispersion. Both realized bootstrap lower bounds were positive, but profitable-active-month rates remained below 60%. Its strict 49-position incremental tier improved v8.73 by only about 0.16%-0.18%. The richer execution-microstructure model used quote advantage, execution-book overround and selected versus nonselected probability gaps. Its 44-position tier reached CNY 29.6929/28.6673 expected profit before deployment, but reduced the 2.5% later expected profit and remained below the 2% replacement threshold.

Applying the unchanged v8.64 deployment rule to that microstructure tier produced CNY 132.2370/121.0358 expected profit and CNY 93.87 maximum drawdown. Relative to v8.74, the 5% path improved 2.75%, but the 2.5% path improved only 1.86% and its later expected profit fell from CNY 55.1992 to CNY 54.7755. Cross-cost governance therefore rejects it. Neither all-month supplementation nor abstention-month fallback passed the replacement gate.

### v8.92-v8.97 candidate and estimator probes

v8.92 removed the model-preceding minimum EV, price-ratio and probability filters while retaining quote sanity, reference depth and the maximum price-ratio guard. Both standalone paths survived: 205/188 positions, average CLV 6.0929%/5.9361%, and monthly bootstrap lower bounds +3.1518%/+10.3122%. The strict cross-cost incremental set nevertheless reproduced almost exactly the v8.73 portfolio, and using v8.92 as a supplement reproduced it exactly. This shows that the Ridge decision boundary, rather than the earlier loose prefilter, already determines the accepted set. The broader implementation is retained as a research capability but does not justify a new runtime policy.

A fixed ExtraTrees estimator reduced average CLV to 3.7888% and produced a -17.6318% bootstrap lower bound on the first cost path, so the second cost run was stopped. Direct 25% quantile regression produced no positions; the pre-existing 40% specification produced only five positions in one month. Nonlinear trees and direct quantile lower-bound models are rejected for the current sample.

### v8.98-v8.101 incremental sizing audit

The 46 v8.73 incremental positions have isolated expected ROI above 7%, so a fixed 1.25 stake multiplier reused the already accepted v8.57 growth limit. After frozen v8.64 deployment it reached CNY 131.6011/119.4926 expected profit with CNY 93.57 drawdown, but improved v8.74 by only 1.37%/1.44%. A more selective rule used the lower 2.5%/5% predicted positive-CLV probability, no uplift below 0.75 and a fixed 1.25 cap. It reached CNY 130.9320/118.9018, only +0.85%/+0.94%, while preserving CNY 93.06 drawdown.

Both sizing variants are rejected by the unchanged 2% materiality gate. The result localizes the current bottleneck: increasing stake on existing incremental positions cannot create enough cross-cost improvement. Further work should improve genuinely new candidate quality and prospective calibration rather than relax risk limits or tune stake multipliers.

### v8.102-v8.111 calibration and estimator probes

Trailing-validation residual corrections by outcome, odds band and source type were tested both as direct prediction shrinkage and as ranking-only adjustments. Direct correction expanded the 2.5% path to 268 positions but produced a -1.3351% bootstrap lower bound; ranking-only correction retained 205 positions but its lower bound was -1.3822%. Ranking by lower CLV times predicted positive-CLV probability reproduced v8.92 exactly, while a fixed 0.50 classifier gate reduced profitable-month coverage. These corrections are rejected because the validation buckets do not generalize across the next-month folds.

Second-best execution quotes and best quotes capped at 102% of the second-best quote produced no eligible positions under the unchanged lower-CLV rule. A market-residual probability blend assigned zero model weight in all 29 validation folds because its mean Brier score did not beat the opening market. Ninety-day recency weighting, Huber regression and 25% residual quantile regression also failed the first 2.5% path. The second cost runs were intentionally stopped after their pre-specified first-path rejection conditions were met.

### v8.112-v8.116 closing-logit target

v8.112 predicts closing minus opening probability in log-odds space, then converts the predicted closing logit back to probability before calculating lower CLV. This keeps equal model movements comparable near 10%, 50% and 90% probabilities without using closing data in the decision frame. The standalone 2.5% path selected 181 positions, achieved 5.7891% average CLV, a 74.03% positive-CLV rate and a +11.3412% monthly bootstrap lower bound. The 5% path selected 147 positions with 6.1875% average CLV, a 76.19% positive-CLV rate and a +11.0540% lower bound. Both paths passed their standalone research gates.

The strict cross-cost incremental replay added 33 directions beyond v8.60 and reached CNY 29.5180/CNY 28.4306 expected profit before deployment. Applying the previously frozen v8.64 monthly rule produced CNY 130.2046/CNY 118.2006 expected profit, CNY 53.7309/CNY 41.7270 later expected profit and CNY 87.60 maximum drawdown. Relative to v8.74, total expected profit improved only 0.29%/0.34%, below the fixed 2% materiality gate, while later expected profit decreased. v8.114 is therefore rejected despite its lower drawdown.

A pre-specified supplemental replay let v8.72 retain every conflict and used v8.112 only for matches absent from the primary path. It added 59 incremental directions. Frozen deployment reached CNY 130.3990/CNY 118.3272 expected profit and improved later expected profit to CNY 55.5075/CNY 43.4357, but the gains over v8.74 were only 0.44%/0.45% and maximum drawdown rose to CNY 94.26. v8.116 also fails materiality. The logit target remains a useful research capability, but v8.74 remains the historical paper champion and no v8.112 artifact is exported or registered.
