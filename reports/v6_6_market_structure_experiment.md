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
