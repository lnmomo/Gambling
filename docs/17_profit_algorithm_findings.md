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

Superseded note: the early SP2 residual-model direction below was the starting point of the research, not the current best candidate. Later no-lookahead and market-bias experiments supersede it. The current strongest historical direction is the market-bias family documented in v19/v20.

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

## Cross-League Rule Search

A new algorithm experiment was added in `scripts/cross_league_rule_search.py`. It is deliberately broader than the SP2-only script:

- Rule pool covers league group, outcome, odds bucket, and EV threshold.
- League groups include `ALL`, `MAJOR_TOP`, `SECOND_DIV`, `EN_LOWER`, and `DRAW_HEAVY_EU`, plus individual leagues.
- Each test month can only select rules using prior monthly rule results.
- Same-match duplicate bets are removed after rule selection.
- Stake mode is fixed 1 unit per bet to measure edge quality without Kelly over-amplifying noisy probabilities.

Results from 2022-08 through 2026-05:

| Experiment | Main Change | Bets | Profit | ROI | Max DD | Active Months | Positive / Negative | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| v1 | League-specific rules, allowed EV >= -0.05 | 256 | -17.30 | -6.76% | 38.39 | 27 | 10 / 17 | Rejected |
| v2 | Recent-degradation gate, EV >= -0.02 | 13 | 5.18 | 39.85% | 2.00 | 6 | 3 / 3 | Not enough sample |
| v3 | Adds predeclared cross-league groups | 137 | 0.75 | 0.55% | 18.52 | 15 | 7 / 8 | Positive but unstable |
| v4 | Adds portfolio-level pause gate | 84 | 3.56 | 4.24% | 10.30 | 6 | 3 / 3 | Not enough recent evidence |
| v5 | Adds LCB rule scoring and cooldown probe | 37 | -9.17 | -24.78% | 12.72 | 3 | 0 / 3 | Rejected |
| v6 | Cooldown probe without LCB scoring | 95 | 3.24 | 3.41% | 10.30 | 10 | 4 / 6 | Not enough evidence |
| v7-fav | Adds market favorite / non-favorite structure | 74 | 8.60 | 11.62% | 9.32 | 11 | 5 / 6 | Not enough sample |
| v7-shape | Adds market shape buckets only | 34 | -13.99 | -41.15% | 14.74 | 7 | 1 / 6 | Rejected |
| v7-model-delta | Adds model-market delta buckets only | 65 | -11.02 | -16.95% | 19.67 | 11 | 4 / 7 | Rejected |
| v8-focus-baseline | Focused draw `[2.8,3.5)`, any + favorite relation | 70 | 7.62 | 10.89% | 9.32 | 10 | 5 / 5 | Not enough sample |
| v8-strength-gap | Adds Elo strength-gap bucket | 68 | 9.67 | 14.22% | 7.20 | 10 | 6 / 4 | Not enough recent evidence |
| v8-goal-env | Adds expected-goal environment bucket | 57 | 17.42 | 30.56% | 6.20 | 11 | 7 / 4 | Not enough recent evidence |
| v8-league-draw-rate | Adds prior league draw-rate bucket | 66 | 5.92 | 8.97% | 10.12 | 10 | 5 / 5 | Not enough recent evidence |
| v8-draw-market-prob | Adds draw market probability bucket | 59 | 12.62 | 21.39% | 6.20 | 12 | 7 / 5 | Not enough recent evidence |
| v9-train12 | v8 default, 12-month model training window | 48 | 3.71 | 7.73% | 9.07 | 10 | 6 / 4 | Not enough recent evidence |
| v9-train24 | v8 default, 24-month model training window | 49 | -15.54 | -31.71% | 18.72 | 5 | 1 / 4 | Rejected |
| v9-train30 | v8 default, 30-month model training window | 42 | -9.46 | -22.52% | 13.14 | 4 | 1 / 3 | Rejected |
| v10-consensus-2 | Rule must be selected by at least 2 training windows | 89 | 10.39 | 11.67% | 6.80 | 8 | 4 / 4 | Not enough evidence |
| v10-consensus-3 | Rule must be selected by at least 3 training windows | 33 | 2.05 | 6.21% | 6.80 | 2 | 1 / 1 | Not enough sample |
| v10-consensus-4 | Rule must be selected by all 4 training windows | 15 | 3.90 | 26.00% | 3.20 | 1 | 1 / 0 | Not enough sample |
| v11-I1-favorite | Diagnostic candidate: Italy Serie A market favorites | 0 | 0.00 | 0.00% | 0.00 | 0 | 0 / 0 | Rejected |
| v11-E2-away | Diagnostic candidate: England League One away selections | 0 | 0.00 | 0.00% | 0.00 | 0 | 0 / 0 | Rejected |
| v11-odds-1.8-2.2 | Diagnostic candidate: favorite odds `[1.8,2.2)` | 14 | 4.99 | 35.64% | 1.00 | 5 | 4 / 1 | Not enough sample |
| v11-odds-1.8-2.2-loose | Same candidate with looser rolling gate | 25 | -4.41 | -17.64% | 10.09 | 8 | 4 / 4 | Rejected |
| v12-market-bias-basket | Market-bias candidates selected by prior months | 1233 | 51.90 | 4.21% | 29.10 | 36 | 22 / 14 | Research candidate |
| v12-I2-draw-default | Italy Serie B draw `[2.8,3.5)` market-bias rule | 692 | 59.68 | 8.62% | 21.00 | 24 | 14 / 10 | Research candidate |
| v12-I2-draw-strict | Same rule with stricter rolling gate | 661 | 55.08 | 8.33% | 21.00 | 23 | 13 / 10 | Positive but unstable |
| v12-I2-draw-lookback18 | Same rule with 18-month rule lookback | 755 | 89.28 | 11.83% | 21.00 | 27 | 15 / 12 | Research candidate |

Interpretation:

- v1 proves that simply expanding the search space is harmful; it over-selects weak `EV >= -0.05` rules.
- v2 proves recent-degradation control works, but it collapses sample size.
- v3 finds a broader structural signal around draw odds `[2.8,3.5)`, especially `ALL|draw|[2.8,3.5)|EV >= -0.02`, but the edge is too thin.
- v4 improves ROI and drawdown by pausing after poor live months, but it stops too much and does not produce enough 2025-26 evidence.
- v5 shows that the initial lower-confidence-bound scoring is not useful yet; it concentrated risk into losing months.
- v6 is better than v4 because cooldown probes allow fresh 2025-26 evidence, but 95 bets and 4 / 6 monthly split still fail the stability standard.
- v7 shows that market favorite relation is useful: the best new rule family is still draw odds `[2.8,3.5)`, especially when the selected draw is not the market favorite. It improves ROI, but sample size and monthly stability still fail the production standard.
- Market-shape buckets and raw model-market delta buckets are rejected for now; both worsened sample-out performance.
- v8 confirms that focusing the search on the discovered family, `draw [2.8,3.5)`, improves stability versus the broad all-outcome search.
- `goal_env=normal_goal` is the best new context feature so far. The effective pattern is normal expected-goal environment + non-favorite draw, mostly SP2/I2 style leagues. It is promising but still too small and slightly negative in the latest season.
- Prior league draw-rate did not help; it selected into a weak 2025-26 window.
- v9 is a major robustness warning. The v8 candidate is highly sensitive to the model training window: 18 months is strongly positive, 12 months is weak and unstable, and 24/30 months are clearly negative. This means v8 is not a stable profitable algorithm.
- `scripts/training_window_sensitivity.py` now automates this check. For the current candidate, `robust_across_windows=false`: only 2 of 4 training windows are profitable, and none has convincing latest-season confirmation.
- v10 adds `scripts/multi_window_consensus_search.py`, where a rule must be selected by multiple training windows before entering the portfolio. This reduces the single-window overfit risk, but it does not solve the edge problem: consensus-2 has more bets but only 4 / 4 monthly split, while consensus-3/4 collapses sample size.
- v11 adds `scripts/candidate_feature_diagnostics.py` for discovery-only feature diagnostics. It found apparent candidates such as I1 market favorites, E2 away selections, and odds `[1.8,2.2)`. When converted back into no-lookahead walk-forward rules, I1/E2 produced no eligible rolling rules, and the `[1.8,2.2)` candidate failed under looser gates. These are rejected for now.
- v12 adds `scripts/market_bias_diagnostics.py` and `scripts/market_bias_walk_forward.py`. This is the first clearly stronger candidate family: Italy Serie B (`I2`) draw odds `[2.8,3.5)` as a pure market-bias rule. It does not depend on the residual model and survives rolling no-lookahead selection with 692 bets, +59.68 units, 8.62% ROI, 24 active months, 14 / 10 month split, and positive profit in every season including 2025-26.
- The broader market-bias basket is positive but less clean. The single I2 draw rule is currently the best research candidate because it is simpler, larger, and more stable than the previous model-derived draw rules.
- v13 adds odds-source sensitivity for the same frozen `I2 draw [2.8,3.5)` rule. The edge survives across average and maximum market odds, both open and close, but weakens on B365 closing odds. This means the rule is not only a B365-open artifact, but the obtainable price matters; production logic should require official SP/market price to still fall inside the validated band and should prefer early/available prices over stale late prices.
- v14 adds a live shadow challenger and an official-SP validation path. `football_agents/market_bias_shadow_strategy.py` freezes the candidate as `I2 draw [2.8,3.5)`. `football_agents/market_bias_official_validation.py` evaluates only the earliest pre-match official SP snapshot and then settles with actual results, so the validation does not use future match outcomes when selecting bets.
- v15 adds `scripts/market_bias_robustness_gate.py`, an overfit firewall for the current market-bias candidate. It reruns the frozen rule across 8 odds sources and 3 rolling-selection profiles, then requires positive ROI, enough sample, more positive than negative months/seasons, non-negative latest-season profit, and drawdown smaller than total profit for each run to pass.
- v16 adds `scripts/market_bias_portfolio_simulation.py`, a settlement-aware capital simulation for the current candidate. It converts the unit-stake research rule into a daily-limit portfolio: daily exposure cap, per-match cap, settlement delay, and optional cooldown decisions based only on already-settled results.
- v17 adds `scripts/market_bias_promotion_gate.py`, a combined promotion gate for market-bias strategies. It merges robustness evidence, settlement-aware portfolio evidence, and official-SP prospective validation into one decision. This prevents a historically profitable rule from being promoted before it has enough real official-SP settlement data.
- v18 adds `scripts/market_bias_candidate_screen.py`, a multi-candidate screening pipeline. It reads discovery diagnostics, filters out vague or recently deteriorating candidates, runs no-lookahead walk-forward on each remaining rule, and applies the settlement-aware portfolio simulation with the current capital policy.
- v19 fixes the robustness-gate CLI so explicit `--rule` values no longer get combined with the default I2 draw rule. It then reruns the B1, SP1, and T1 candidates as pure rules. This matters because the first rerun was contaminated by the default rule and overstated candidate stability.

Odds-source sensitivity, 2022-08 through 2026-05:

| Odds Source | Bets | Profit | ROI | Max DD | Active Months | Positive / Negative | Latest Season | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| AVG_OPEN | 871 | 82.76 | 9.50% | 22.50 | 28 | 17 / 11 | +28.77 | Research candidate |
| MAX_OPEN | 813 | 100.37 | 12.35% | 18.36 | 30 | 18 / 12 | +36.25 | Research candidate |
| AVG_CLOSE | 863 | 66.79 | 7.74% | 28.54 | 28 | 17 / 11 | +23.17 | Research candidate |
| MAX_CLOSE | 711 | 42.35 | 5.96% | 22.85 | 26 | 16 / 10 | +13.96 | Research candidate |
| B365_OPEN | 691 | 60.68 | 8.78% | 21.00 | 24 | 14 / 10 | +20.94 | Research candidate |
| B365_CLOSE | 688 | 26.89 | 3.91% | 23.93 | 24 | 11 / 13 | -13.28 | Not enough recent evidence |
| PS_OPEN | 390 | 53.65 | 13.76% | 16.63 | 14 | 9 / 5 | +26.55 | Positive but unstable |
| PS_CLOSE | 472 | 45.42 | 9.62% | 24.68 | 16 | 9 / 7 | +24.40 | Positive but unstable |

Interpretation of v13:

- The signal is strongest when the available draw price is still reasonably high (`AVG_OPEN`, `MAX_OPEN`).
- B365 close has a negative latest season and worse month balance, so the algorithm must not blindly bet after the market has moved.
- `AVG_OPEN` is the most realistic research proxy because it averages market prices instead of cherry-picking the best book.
- `MAX_OPEN` is useful as an upper-bound scenario, but it assumes the system can actually obtain the best available price.
- The next production candidate should therefore be `I2 draw [2.8,3.5)` with an odds-source/price-quality gate, not a generic Serie B draw rule.

Official-SP prospective validation status:

- Command: `python -m football_agents.cli validate-market-bias-official-sp --output reports/official_sp_market_bias_validation/summary.json`
- Current database result: 13 settled official-SP samples, 0 matches for the frozen I2 draw rule.
- Interpretation: the football-data evidence is strong enough for shadow validation, but Chinese official SP evidence is still missing. This rule must remain a research/shadow challenger until enough official-SP samples settle.
- Settlement fix: market-bias shadow additions now settle using the selected draw SP stored in `true_odds_estimate.market_bias_shadow_candidate.selected_sp`, not the baseline recommendation SP. This prevents added `NO_BET -> DRAW` shadow picks from being counted as zero-stake/no-price outcomes.

Robustness gate result:

- Command: `python scripts/market_bias_robustness_gate.py --output-dir reports/market_bias_robustness_gate_i2_draw`
- Runs: 24 (`8` odds sources x `3` rolling-selection profiles)
- Passed runs: 22 / 24
- Odds sources with at least one passing profile: 8 / 8
- Rolling profiles with at least one passing source: 3 / 3
- Decision: `RESEARCH_CANDIDATE_SHADOW_VALIDATION`

The gate strengthens the historical case for `I2 draw [2.8,3.5)`: it is not just one month, one source, or one rolling parameter. However, the two failing runs are both `B365_CLOSE` configurations with negative latest-season evidence. That keeps the practical rule narrow: this is an early/available-price candidate, not a generic late-price draw strategy.

Settlement-aware portfolio simulation:

- Command: `python scripts/market_bias_portfolio_simulation.py --odds-source AVG_OPEN --output-dir reports/market_bias_portfolio_simulation_i2_draw_avg_open_default`
- Default capital policy after testing: daily exposure cap `100`, per-match cap `10`, settlement delay `1` day, no cooldown.
- Result: 871 bets, total staked `8710`, profit `827.60`, ROI `9.50%`, max drawdown `225.00`, positive / negative months `17 / 11`, positive / negative seasons `3 / 1`.
- Full daily allocation variant (`max_single_stake=100`) produces higher nominal profit (`2123.53`) but worse drawdown (`1056.57`), lower ROI (`8.07%`), and weaker month balance (`15 / 13`). It is not the preferred capital policy.
- Cooldown variants also underperformed. With `max_single_stake=10`, no cooldown produced ROI `9.50%` and month balance `17 / 11`; `stop2_cd7` produced month balance `13 / 15`; `stop3_cd7` produced ROI `6.62%` and month balance `15 / 13`.

Interpretation: forcing the full 100 daily limit into sparse days amplifies noise. The better current policy is "up to 100 per day, at most 10 per match", not "must invest 100 every active day." This keeps the rule investable while avoiding excessive concentration in days with only one or two qualifying matches.

Promotion gate result:

- Command: `python scripts/market_bias_promotion_gate.py --output reports/market_bias_promotion_gate_i2_draw/summary.json`
- Decision: `SHADOW_READY_PRODUCTION_BLOCKED`
- Historical robustness: passed (`22 / 24` runs, `8 / 8` sources, `3 / 3` profiles)
- Settlement-aware portfolio: passed (`+827.60`, `9.50%` ROI, drawdown/profit `0.2719`, positive / negative months `17 / 11`)
- Official-SP prospective validation: failed for production (`0` settled candidates, `0` active official-SP months)

Interpretation: the current algorithm is now strong enough to keep running as a frozen shadow strategy, but not strong enough for production betting. The hard production blocker is not historical football-data performance; it is missing prospective settlement on Chinese official SP.

Multi-candidate screen:

- Command: `python scripts/market_bias_candidate_screen.py --top-n 12 --output-dir reports/market_bias_candidate_screen_top12_avg_open`
- Primary screen source: `AVG_OPEN`
- Capital policy: daily cap `100`, per-match cap `10`, no cooldown
- Candidates screened: 12
- Candidates passing portfolio screen: 6

Top non-duplicate candidates:

| Candidate | Portfolio Bets | Profit | ROI | Max DD | Months | Seasons | Status |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `B1 [2.8,3.5) / market prob [0.20,0.28)` | 126 | 311.50 | 24.72% | 112.40 | 10 / 8 | 2 / 1 | Needs full robustness |
| `SP1 home / market prob [0.55,1.00]` | 166 | 212.50 | 12.80% | 37.80 | 11 / 6 | 3 / 0 | Needs full robustness |
| `I2 draw / odds [2.8,3.5)` | 871 | 827.60 | 9.50% | 225.00 | 17 / 11 | 3 / 1 | Full robustness passed |
| `T1 market prob [0.55,1.00]` | 294 | 154.70 | 5.26% | 53.90 | 16 / 12 | 3 / 1 | Needs full robustness |

Interpretation: I2 is no longer the only viable historical candidate. However, only I2 has completed the full multi-source robustness gate so far. The new B1/SP1/T1 candidates are promising enough to test, but they are not promotion candidates until they pass the same full gate.

Pure-candidate robustness gate:

| Candidate | Rule | Passed Runs | Source Passes | Profile Passes | Decision | Interpretation |
| --- | --- | ---: | ---: | ---: | --- | --- |
| I2 draw | `league|outcome|odds_bucket=I2|draw|[2.8,3.5)` | 22 / 24 | 8 / 8 | 3 / 3 | `RESEARCH_CANDIDATE_SHADOW_VALIDATION` | Strong historical baseline; official-SP sample still blocks production |
| B1 odds/prob band | `league|odds_bucket|market_prob_bucket=B1|[2.8,3.5)|[0.20,0.28)` | 2 / 24 | 2 / 8 | 2 / 3 | `KEEP_SHADOW_ONLY` | Rejected as a primary rule; high AVG_OPEN ROI was not cross-source robust |
| SP1 home high market probability | `league|outcome|market_prob_bucket=SP1|home|[0.55,1.00]` | 23 / 24 | 8 / 8 | 3 / 3 | `RESEARCH_CANDIDATE_SHADOW_VALIDATION` | Best high-ROI pure challenger, but smaller sample than I2 |
| T1 high market probability | `league|market_prob_bucket=T1|[0.55,1.00]` | 15 / 24 | 5 / 8 | 3 / 3 | `RESEARCH_CANDIDATE_SHADOW_VALIDATION` | Viable secondary candidate, but weaker on AVG/B365 recent evidence |

Pure-candidate AVG_OPEN portfolio simulation, daily cap `100`, per-match cap `10`, no cooldown:

| Candidate | Bets | Total Staked | Profit | ROI | Max DD | Positive / Negative Months | Positive / Negative Seasons |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| I2 draw | 871 | 8710.00 | 827.60 | 9.50% | 225.00 | 17 / 11 | 3 / 1 |
| SP1 home high market probability | 166 | 1660.00 | 212.50 | 12.80% | 37.80 | 11 / 6 | 3 / 0 |
| T1 high market probability | 1165 | 11639.99 | 982.81 | 8.44% | 178.60 | 22 / 12 | 4 / 0 |
| I2 + SP1 combo | 1037 | 10370.00 | 1040.10 | 10.03% | 143.10 | 19 / 12 | 4 / 0 |

Interpretation of v19:

- `SP1 home / market probability [0.55,1.00]` is the strongest high-ROI pure challenger. It passed 23 / 24 robustness runs, but only has 166 AVG_OPEN portfolio bets.
- The best current historical portfolio is the `I2 + SP1` combo: it keeps I2's sample size, adds SP1's high-ROI home-favorite signal, raises profit from `827.60` to `1040.10`, and lowers max drawdown from `225.00` to `143.10`.
- `T1 market probability [0.55,1.00]` is useful but less clean. Its AVG_OPEN and B365 variants show latest-season weakness, so it should be lower priority than SP1.
- The B1 rule is a good example of why the robustness gate is necessary: it looked excellent in the first AVG_OPEN screen, but failed cross-source validation.
- None of these candidates should become production betting rules before official Chinese SP prospective validation. Historical football-data profitability is necessary evidence, not sufficient evidence.

SP1 implementation status:

- `football_agents/market_bias_shadow_strategy.py` now supports multiple frozen market-bias challengers instead of only I2.
- Added strategy `market-bias-sp1-home-market-prob-0.55-1.00-v1`.
- Rule: Spanish La Liga (`SP1`, `Spanish La Liga`, or `La Liga`) + home outcome + devigged official home market probability `>= 0.55`.
- Live shadow behavior: if the baseline says `NO_BET` and the SP1 rule matches, the shadow record recommends `HOME` with the observed official home SP.
- Official-SP validation can now validate all frozen candidates or one candidate via `--strategy-id`.
- Current database check: `validate-market-bias-official-sp --strategy-id market-bias-sp1-home-market-prob-0.55-1.00-v1` found `13` settled official-SP samples, `0` SP1 candidates. This means the code path is ready, but production validation is still blocked by missing prospective official-SP samples.
- Pure SP1 promotion gate report: `reports/market_bias_promotion_gate_sp1_home_prob55_100_pure/summary.json`.
- SP1 promotion decision: `SHADOW_READY_PRODUCTION_BLOCKED`.
- SP1 passed every historical and portfolio blocking gate: robustness pass rate `23 / 24`, source passes `8 / 8`, profile passes `3 / 3`, pure portfolio profit `212.50`, ROI `12.80%`, month balance `11 / 6`, season balance `3 / 0`, drawdown/profit `0.1779`.
- SP1 failed only production official-SP gates: settled official candidates `0 / 100`, active official months `0 / 12`, official ROI `0.0%`, official month balance `0 / 0`.

I2 + SP1 combo status:

- Combo rule set: `I2 draw [2.8,3.5)` plus `SP1 home / market probability [0.55,1.00]`.
- Robustness gate report: `reports/market_bias_robustness_gate_i2_sp1_combo/summary.json`.
- Portfolio report: `reports/market_bias_portfolio_simulation_i2_sp1_combo_avg_open_default/summary.json`.
- I2 official-SP report: `reports/official_sp_market_bias_validation/summary.json`.
- I2 promotion gate report: `reports/market_bias_promotion_gate_i2_draw/summary.json`.
- I2 profit algorithm scorecard: `reports/market_bias_profit_algorithm_scorecard_i2_draw/summary.json`.
- Combo research scorecard: `reports/market_bias_profit_algorithm_scorecard_i2_sp1_combo/summary.json`.
- Combo robustness: `22 / 24` source/profile runs passed, `8 / 8` sources passed at least one profile, `3 / 3` rolling profiles passed.
- Combo portfolio: 1037 bets, total staked `10370.00`, profit `1040.10`, ROI `10.03%`, max drawdown `143.10`, positive / negative months `19 / 12`, positive / negative seasons `4 / 0`.
- Rule contribution: I2 contributes 871 bets, `827.60` profit, `9.50%` ROI; SP1 contributes 166 bets, `212.50` profit, `12.80%` ROI.
- Combo official-SP validation now uses strategy id `market-bias-i2-draw-plus-sp1-home-v1`, expanded to the I2 and SP1 leaf rules. Current database result: 13 settled official-SP samples, 0 combo candidates.
- Combo promotion decision: `SHADOW_READY_PRODUCTION_BLOCKED`. Historical and portfolio blocking gates pass; production remains blocked only by official-SP prospective sample gates.
- Combo profit scorecard after the multi-window gate: `59.59 / 100`, pre-window tier `SHADOW_READY_PRODUCTION_BLOCKED`, final deployment tier `RESEARCH_ONLY_UNSTABLE_WINDOWS`. Historical robustness is full score `30 / 30` and settlement-aware portfolio is `24.59 / 25`, but the 12-month rolling validation pass rate is only `7 / 12`.
- I2 standalone profit scorecard: `reports/market_bias_profit_algorithm_scorecard_i2_draw/summary.json`. It remains `SHADOW_READY_PRODUCTION_BLOCKED` after multi-window validation because it passes `8 / 12` windows across `AVG_OPEN` and `AVG_CLOSE`.
- Live shadow metrics now include `market_bias_strategy_metrics`. This reports I2 leaf strategy performance and can still aggregate portfolio research groups, so prospective samples can be monitored without manually parsing JSON payloads.
- `football_agents.market_bias_monitor.MarketBiasMonitorService` now refreshes the I2 shadow metrics report, official-SP validation report, promotion gate report, and profit scorecard in one repeatable workflow.
- CLI command: `python -m football_agents.cli refresh-market-bias-monitor`.
- If no shadow config is running, the monitor automatically creates and starts `market-bias-i2-draw-shadow-monitor` in `SHADOW` mode. This removes the previous manual setup blocker for prospective sample collection.
- Background scheduler task: `market_bias_shadow_monitor`. It runs on service startup and then on the configured background interval, alongside official SP, external odds/news/weather, features, history, backtest, and governance tasks.
- Current local monitor refresh now reports default `strategy_id` as `market-bias-i2-draw-2.8-3.5-v1`. Existing older shadow config ids can still be evaluated, but new market-bias recommendations only use the I2 rule unless a future candidate passes the multi-window gate.
- Pending shadow evaluation is now automatic. When results are present, `MarketBiasMonitorService` evaluates pending shadow predictions against stored results and official closing SP. Current local state: 30 shadow predictions evaluated, 15 still missing results, 17 evaluated rows had no official closing SP and therefore no CLV.
- The same monitor now scans the current official match pool for live I2 candidates and separate research watchlist candidates before reporting. Current local scan: 100 official matches scanned, 55 missing usable official odds, 0 I2 market-bias candidates. Therefore the current blocker is not report plumbing; the current official schedule/odds pool has not produced a qualifying I2 candidate yet.
- Official-SP funnel diagnostics now explain the production blocker directly: `reports/official_sp_market_bias_funnel_i2_draw/summary.json`.
- Current funnel: 28 opening pre-match official-SP samples, 28 valid 1X2 samples, 13 settled opening samples, 0 I2 opening samples, 0 I2 target-band samples. Top leagues are World Cup (`22`) and Finnish Veikkausliiga (`6`). Blocker: `no I2 opening official SP samples`.

Current best algorithmic direction is therefore:

1. Downgrade `I2 draw [2.8,3.5)` from shadow-ready to research-only. The refreshed 12-month multi-window gate shows only `3 / 12` passed windows, so the old full-period profit is not stable enough for allocation.
2. Keep the `I2 + SP1` combo as research-only. It remains profitable in aggregate, but also passes only `3 / 12` windows under the refreshed gate.
3. Reject `SP1 home / market probability [0.55,1.00]` as a standalone allocation candidate for now; it has `0 / 12` passed windows and negative AVG_CLOSE evidence.
4. Keep `T1 market probability [0.55,1.00]` as a secondary challenger, pending stricter recent-season checks.
5. Reject the B1 odds/probability band as a primary candidate unless future data changes its cross-source behavior.
6. Keep the model-derived normal-goal non-favorite draw rule as secondary research only.
7. Add price-quality gating: require the live official/market SP to remain within the validated band and reject stale prices that have already collapsed below the edge window.
8. Treat the 18-month model training window as a research candidate only, not a production setting.
9. Keep feature diagnostics as a discovery tool only; every discovered pattern must be re-tested through walk-forward rules.
10. Do not keep market-shape, raw model-delta, prior league draw-rate, I1/E2 diagnostic candidates, odds `[1.8,2.2)`, or the current LCB score as default selectors.
11. Keep cross-league group rules, recent-degradation filtering, portfolio-level risk gating, cooldown/probe behavior, and multi-window consensus as rejection/risk filters.
12. Use `scripts/market_bias_robustness_gate.py` as the promotion firewall for any future market-bias candidate. A candidate may enter shadow validation only after it survives multi-source and multi-profile checks; it may enter production only after official-SP prospective settlement also passes.
13. Use settlement-aware portfolio simulation before any capital-policy change. The current best research capital policy is daily cap `100`, per-match cap `10`, no cooldown.
14. Use `scripts/market_bias_promotion_gate.py` as the historical/official-SP promotion decision, but require the scorecard to apply the multi-window gate after it. The current scorecard state is `RESEARCH_ONLY_UNSTABLE_WINDOWS`, so it should not influence live shadow or production betting.
15. Use `scripts/market_bias_profit_algorithm_scorecard.py` as the unified evidence score. It combines robustness, settlement-aware portfolio, cross-source validation, official-SP prospective validation, and no-lookahead governance into a single deployment tier.
16. Use `scripts/market_bias_multi_window_optimizer.py` before promotion. It slices full no-lookahead walk-forward bets into rolling validation windows, so a candidate cannot be promoted merely because the full-period total profit is positive.
17. Use `scripts/market_bias_candidate_screen.py` to keep searching beyond I2/SP1. A candidate passing the screen must still pass full robustness, settlement-aware portfolio simulation, multi-window validation, and official-SP prospective validation before promotion.

## Multi-Window Stability Gate

Command:

`python scripts/market_bias_multi_window_optimizer.py --odds-sources AVG_OPEN,AVG_CLOSE --window-months 12 --step-months 6 --output-dir reports/market_bias_multi_window_optimizer_i2_sp1_default`

This gate first runs the normal no-lookahead monthly walk-forward across the full history, then slices the resulting historical candidate bets into rolling 12-month validation windows. That preserves the original rule that a bet can only be selected from prior-month evidence, while preventing a candidate from passing because one long profitable period hides unstable windows.

Default candidate result:

| Candidate | Window Passes | Source Passes | Combined ROI | Worst Window ROI | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| `I2 draw [2.8,3.5)` | 3 / 12 | 2 / 2 | 2.57% | -16.03% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `I2 + SP1 combo` | 3 / 12 | 2 / 2 | 2.57% | -18.42% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `SP1 home prob [0.55,1.00]` | 0 / 12 | 0 / 2 | 2.56% | -26.67% | `REJECT_UNSTABLE` |

Refreshed scorecard:

- Report: `reports/market_bias_profit_algorithm_scorecard_i2_draw/summary.json`.
- Deployment tier: `RESEARCH_ONLY_UNSTABLE_WINDOWS`.
- Multi-window component: `3 / 12` passed windows, pass rate `0.25`, combined ROI `2.57%`, worst window ROI `-16.03%`.
- Interpretation: the historical I2 edge remains a useful research lead, but it is no longer allowed to influence live shadow allocation until a revised rule passes the multi-window gate.

Interpretation:

- The previous combo had the best full-period profit, but it does not pass the current multi-window threshold (`0.5833 < 0.60`).
- I2 standalone is now the cleaner algorithmic baseline: less exciting, but more stable across validation windows.
- This is closer to the actual objective: find a repeatable algorithm, not the most profitable historical mixture.
- Implementation update: SP1 is no longer returned by `find_market_bias_shadow_candidates`. It is reported as `RESEARCH_ONLY_UNSTABLE_WINDOWS` in the research watchlist, so it cannot create shadow picks or production recommendations until rolling-window stability improves.

## I2 Odds-Band Grid Search

`scripts/market_bias_i2_band_grid_search.py` now searches nearby I2 draw odds bands instead of assuming `[2.8,3.5)` is optimal. Each candidate band is evaluated by the same no-lookahead walk-forward process and then sliced into rolling 12-month validation windows.

Local AVG-only check:

`python scripts/market_bias_i2_band_grid_search.py --min-low 2.6 --max-low 3.0 --min-width 0.5 --max-width 0.7 --step 0.2 --odds-sources AVG_OPEN,AVG_CLOSE --output-dir reports/market_bias_i2_band_grid_search_local`

Result:

| Band | Window Passes | Combined ROI | Worst Window ROI | Decision |
| --- | ---: | ---: | ---: | --- |
| `[2.60,3.10)` | 8 / 12 | 9.62% | 0.28% | `MULTI_WINDOW_SHADOW_CANDIDATE` |
| `[2.80,3.50)` | 8 / 12 | 8.85% | -5.48% | `MULTI_WINDOW_SHADOW_CANDIDATE` |

AVG/MAX open-close check:

`python scripts/market_bias_i2_band_grid_search.py --min-low 2.6 --max-low 2.8 --min-width 0.5 --max-width 0.7 --step 0.2 --odds-sources AVG_OPEN,AVG_CLOSE,MAX_OPEN,MAX_CLOSE --output-dir reports/market_bias_i2_band_grid_search_avg_max`

Result:

| Band | Window Passes | Combined ROI | Worst Window ROI | Worst Source ROI | Decision |
| --- | ---: | ---: | ---: | ---: | --- |
| `[2.80,3.30)` | 15 / 24 | 10.64% | -12.23% | 4.07% | `MULTI_WINDOW_SHADOW_CANDIDATE` |
| `[2.80,3.50)` | 14 / 24 | 9.07% | -5.48% | 5.53% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `[2.60,3.30)` | 13 / 24 | 9.76% | -10.60% | 1.95% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `[2.60,3.10)` | 10 / 24 | 10.95% | 0.00% | 0.00% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |

Interpretation:

- `[2.80,3.30)` is now the strongest narrow-band challenger by four-source pass rate.
- It should not replace the live I2 rule yet: its worst rolling window is worse than `[2.80,3.50)`, and the improvement relies heavily on `MAX_CLOSE`.
- `[2.60,3.10)` looked very smooth on AVG sources but failed to generalize to MAX_OPEN, so it is not robust enough.
- Current action: keep live shadow rule at `[2.80,3.50)` and treat `[2.80,3.30)` as the next candidate for full robustness-gate and official-SP prospective testing.

Formal `[2.80,3.30)` challenger package:

- Robustness report: `reports/market_bias_robustness_gate_i2_draw_2p80_3p30/summary.json`.
- Portfolio report: `reports/market_bias_portfolio_simulation_i2_draw_2p80_3p30_avg_open_default/summary.json`.
- Promotion report: `reports/market_bias_promotion_gate_i2_draw_2p80_3p30/summary.json`.
- Scorecard: `reports/market_bias_profit_algorithm_scorecard_i2_draw_2p80_3p30/summary.json`.

Formal result:

| Candidate | Robust Runs | Portfolio ROI | Portfolio Profit | Max DD | Month Split | Multi-Window | Scorecard |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: |
| I2 `[2.80,3.30)` | 21 / 24 | 5.47% | 410.60 | 223.10 | 16 / 13 | 15 / 24 | 57.12 |
| I2 `[2.80,3.50)` | 22 / 24 | 9.50% | 827.60 | 225.00 | 17 / 11 | 8 / 12 AVG-only | 59.18 |

Decision:

- `[2.80,3.30)` is legitimate enough for research shadow comparison, but not enough to replace the current default.
- The current wider `[2.80,3.50)` rule still has better profit, better scorecard, and similar drawdown in the default AVG_OPEN capital simulation.
- If official SP tends to cluster in `[2.80,3.30)`, the narrow challenger may become practically better. That can only be proven by prospective official-SP settlement, not historical football-data CSV alone.

## Official-SP Prospective Blocker

Command:

`python -m football_agents.cli diagnose-market-bias-official-sp --output reports/official_sp_market_bias_funnel_i2_draw/summary.json`

Current result:

| Funnel Step | Count |
| --- | ---: |
| Opening pre-match official-SP samples | 28 |
| Valid three-way samples | 28 |
| Settled opening samples | 13 |
| I2 opening samples | 0 |
| I2 settled samples | 0 |
| I2 `[2.80,3.50)` samples | 0 |

Interpretation:

- The official-SP blocker is not the I2 odds band, settlement logic, or promotion gate.
- The current official pool contains World Cup and Finnish league matches, but no Italian Serie B official-SP samples.
- More algorithm tuning cannot prove production profitability until the official feed contains matching I2 fixtures with pre-match SP snapshots and settled results.
- The correct next data action is to keep the hourly official-SP collector running through periods where Chinese official pages include Italian Serie B, or add a separate prospective source that records official-like SP for I2 before kickoff.

## Worldwide Football-Data Extension

`scripts/monthly_shadow_backtest.py` and `scripts/cross_league_rule_search.py` now support the worldwide `football-data/new/*.csv` format, where files use `Home/Away/HG/AG` and often provide closing odds only. This lets the same market-bias diagnostic, walk-forward, robustness, and portfolio tools test leagues such as `FIN`, `JPN`, `RUS`, `AUT`, and `SWE` instead of treating them as unrelated one-off data.

Current official pool relevance:

- Current local official pool is mostly World Cup plus Finnish Veikkausliiga.
- The international results database has many World Cup/national-team results but no 1X2 odds, so it can help team-history features but cannot validate an odds-edge strategy.
- `FIN.csv` does have odds and results, so it was tested directly.

FIN result:

- Discovery found weak apparent patterns, e.g. `FIN away / market probability [0.28,0.34)`.
- Full rolling robustness rejected them: `0 / 12` source/profile runs passed.
- Settlement-aware portfolio selected no bets under the default no-lookahead gate.
- Decision: do not add a FIN live/shadow betting rule now. Current Finnish matches should remain unbet unless a future candidate passes the full gate.

Worldwide close-odds scan:

| Candidate | Robustness Passes | Source Passes | Profile Passes | Decision | Notes |
| --- | ---: | ---: | ---: | --- | --- |
| `JPN away / market probability [0.28,0.34)` | 4 / 12 | 2 / 4 | 3 / 3 | `KEEP_SHADOW_ONLY` | Best new worldwide research candidate, but not source-diverse enough |
| `RUS home / odds [2.2,2.8)` | 1 / 12 | 1 / 4 | 1 / 3 | `KEEP_SHADOW_ONLY` | Too source-dependent |
| `AUT odds [4.0,5.0) / market probability [0.20,0.28)` | 2 / 12 | 1 / 4 | 2 / 3 | `KEEP_SHADOW_ONLY` | Good PS-only signal, weak cross-source behavior |

JPN portfolio check, daily cap `100`, per-match cap `10`, no cooldown:

| Odds Source | Bets | Total Staked | Profit | ROI | Max DD | Months | Seasons |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| AVG_CLOSE | 339 | 3390.00 | 211.40 | 6.24% | 165.80 | 27 / 20 | 7 / 3 |
| MAX_CLOSE | 456 | 4560.00 | 770.70 | 16.90% | 156.90 | 42 / 25 | 10 / 2 |
| PS_CLOSE | 402 | 4020.00 | 192.40 | 4.79% | 182.40 | 29 / 28 | 7 / 4 |

Interpretation:

- `JPN away / market probability [0.28,0.34)` is the next best research candidate after I2/SP1, but it is not production-ready.
- The signal is much stronger on `MAX_CLOSE` than `PS_CLOSE`, which is a warning that obtainable price quality may explain a large part of the edge.
- The latest PS-close season is weak, so this rule should not be added to live recommendations without prospective Chinese official-SP validation.
- It may be added later as a shadow-only challenger if the official pool starts containing J1 matches and if the promotion gate is configured to label it as unpromoted research.
- Implementation status: `football_agents.market_bias_shadow_strategy` now exposes this JPN rule only as a research watchlist candidate, and `MarketBiasMonitorService` reports it under `live_candidate_scan.research_watchlist`. It is deliberately not returned by `find_market_bias_shadow_candidates`, so it does not create shadow picks or production recommendations.
- Current local monitor refresh: 100 official matches scanned, 55 missing usable official odds, 0 I2/SP1 shadow candidates, 0 JPN research-watch candidates.

Official-pool relevance diagnostic:

- `football_agents.market_bias_pool_relevance.diagnose_market_bias_official_pool_relevance` now maps the live Chinese official pool to available market-bias validation packages.
- CLI:
  `python -m football_agents.cli diagnose-market-bias-official-pool --output reports/market_bias_official_pool_relevance/summary.json`
- The market-bias monitor writes the same report during `refresh-market-bias-monitor`, so the workflow can show whether a NO_BET day is caused by no odds, no validated league coverage, or a failed research rule.

Current local report:

| League | Matches | With Odds | Validation Coverage | Blocker |
| --- | ---: | ---: | --- | --- |
| World Cup | 97 | 42 | `REJECTED_WORLD_CUP_RULE` | World Cup odds history exists, but no-lookahead portfolio validation rejected allocation rules |
| FIN | 24 | 12 | `REJECTED_RESEARCH_RULE` | FIN historical rule failed robustness |
| International | 2 | 0 | `NO_MARKET_BIAS_VALIDATION_SOURCE` | no latest official 1X2 odds |

Interpretation:

- The current official pool has 0 validated market-bias shadow candidates because it does not contain I2 fixtures.
- This is an algorithm/data-coverage blocker, not a reason to force daily allocation.
- A profitable system should be allowed to hold cash when the live pool is outside validated strategy coverage. Forcing bets in World Cup or FIN after their stability gates failed would turn the strategy from evidence-driven into curve-fitting.

FIN current-pool retest:

- Strict multisource discovery (`AVG_CLOSE` + `PS_CLOSE`) produced 0 FIN candidates.
- Single-source discovery followed by `AVG_CLOSE`, `PS_CLOSE`, and `MAX_CLOSE` validation produced 12 candidate rows and 0 passes.
- The best visible FIN price-shape candidate, `FIN / odds [2.8,3.5) / market_non_favorite`, lost money across all three close-odds validation sources:
  - `AVG_CLOSE`: 409 bets, -128.00, -3.13% ROI.
  - `PS_CLOSE`: 540 bets, -288.20, -5.34% ROI.
  - `MAX_CLOSE`: 433 bets, -189.30, -4.37% ROI.
- Decision: do not add FIN to live shadow or allocation. If FIN remains important because the official pool contains it often, the next experiment must be a new FIN-specific feature model, not a looser market-bias threshold.

FIN residual-feature model retest:

- Because the current official pool contains many FIN matches, FIN was also tested with the leakage-free residual probability framework rather than only market-bias buckets.
- Command family:
  `python scripts/cross_league_rule_search.py --seasons FIN --first-month 2015-04 --last-month 2025-10 --training-months 24 --lookback-months 12 --min-active-months 4 --min-bets 20 --min-roi 0.02 --max-rules 3 --min-league-matches 300 --ev-thresholds=-0.02,-0.01,0.0,0.01 --recent-active-months 3 --min-recent-roi -0.02 --lcb-z 0.25 --structure-modes any,fav_relation,goal_env,draw_market_prob --outcome-scope home,draw,away --odds-bucket-scope ALL --league-group-scope FIN`
- The experiment uses only prior months to select rules and validates on the next month. Same-day results are hidden until settlement.

| FIN Residual Experiment | Bets | Profit | ROI | Active Months | Month Balance | Verdict |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| No portfolio gate | 41 | -2.10 | -5.12% | 14 | 6 / 8 | `rejected_negative_edge` |
| Balanced portfolio gate | 33 | -1.71 | -5.18% | 10 | 5 / 5 | `rejected_negative_edge` |

Interpretation:

- The residual model did find appealing historical rule candidates, e.g. FIN away `[2.2,2.8)` and FIN home `[1.8,2.2)`, but they did not hold up consistently in the next-month samples.
- The balanced gate reduced exposure but did not turn the strategy profitable, so the failure is not mainly a bankroll/allocation issue.
- FIN remains rejected for live allocation. It can be revisited only with a materially different model family or more predictive live features; simply lowering thresholds would increase overfitting risk.

Cross-league residual-model audit:

- Existing `cross_league_rule_search*`, `fixed_sp2*`, and `residual_walk_forward*` reports were re-ranked by sample size, profit, ROI, active months, drawdown, and stability verdict.
- Very high ROI rows such as `residual_walk_forward_profitable_2024_11` and `fixed_sp2_draw_22_28` were rejected as small-sample artifacts: 8 and 17 bets are not enough evidence for a profitable algorithm.
- The only residual-model family with enough sample to examine seriously is SP2 draw / SP2 residual edge.

SP2 residual draw audit:

| Strategy | Window | Bets | Profit | ROI | Max DD | Active Months | Month Balance | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `fixed_sp2_edge_strategy` | 2022-08..2025-05 | 130 | +11.72 | 8.30% | 15.92 | 29 | 15 / 14 | `candidate_positive_but_unstable` |
| `fixed_sp2_draw_all` | 2022-08..2025-05 | 112 | +12.86 | 10.44% | 15.17 | 28 | 16 / 12 | `candidate_positive_but_unstable` |
| `fixed_sp2_draw_all_5season` | 2022-08..2026-05 | 113 | +11.86 | 9.55% | 15.17 | 29 | 16 / 13 | `not_enough_recent_evidence` |
| `fixed_sp2_draw_evminus005_5season` | 2022-08..2026-05 | 418 | +18.08 | 4.21% | 20.76 | 40 | 18 / 21 | `candidate_positive_but_unstable` |
| `fixed_sp2_draw_all_5season_balanced_gate` | 2022-08..2026-05 | 48 | +7.35 | 13.93% | 12.10 | 11 | 6 / 5 | `not_enough_sample` |
| `fixed_sp2_draw_all_5season_conservative_gate` | 2022-08..2026-05 | 38 | +0.25 | 0.63% | 12.10 | 9 | 4 / 5 | `not_enough_sample` |
| `fixed_sp2_draw_all_min025_5season_balanced_gate` | 2022-08..2026-05 | 35 | +6.67 | 39.17% | 4.30 | 8 | 3 / 5 | `not_enough_sample` |
| `fixed_sp2_draw_all_min025_5season_conservative_gate` | 2022-08..2026-05 | 27 | +1.62 | 13.10% | 4.30 | 7 | 2 / 5 | `not_enough_sample` |

Interpretation:

- SP2 draw is better than the rejected FIN experiments and worth keeping as a research benchmark.
- It is not yet the requested "赚钱算法": drawdown is larger than profit in the main variants, 2023-24 is negative, and stricter portfolio gates either leave too little sample or collapse the edge.
- Reducing minimum stake from `1.00` to `0.25` improves the drawdown/profit ratio in the balanced gate (`4.30 / 6.67 = 0.645`), but it also leaves only 35 bets and a weak month balance (`3 / 5`). That means stake sizing reduces pain but does not prove edge stability.
- The useful lesson is algorithmic: residual-model candidates must pass a stability-adjusted gate, not just positive all-period ROI.
- Current decision: keep SP2 draw as `RESEARCH_BENCHMARK_ONLY`; do not connect it to live allocation or shadow recommendations yet.

Residual strategy scorecard:

- Script: `scripts/residual_strategy_scorecard.py`.
- Report: `reports/residual_strategy_scorecard/summary.json`.
- Scope: 65 residual / relative-value strategy reports, including `cross_league_rule_search`, `fixed_sp2`, and `residual_walk_forward` families.
- Current tier counts:
  - `REJECT_SMALL_SAMPLE`: 32
  - `REJECT_NEGATIVE_EDGE`: 24
  - `REJECT_MONTH_BALANCE`: 5
  - `RESEARCH_POSITIVE_UNSTABLE_DRAWDOWN`: 3
  - `REJECT_TOO_FEW_ACTIVE_MONTHS`: 1
  - `SHADOW_RESEARCH_CANDIDATE`: 0
- Promotion rule requires at least 100 bets, at least 24 active months, more positive months than negative months, drawdown/profit no worse than 1.0, and no negative latest-season profit when that field is available.
- Current conclusion: no residual / relative-value strategy is ready for shadow allocation. The best-looking `cross_league_rule_search_v8_*` experiments are rejected for sample size, while the stronger SP2 draw variants are rejected for drawdown or month-balance weakness.

Generic market-bias walk-forward selector hardening:

- Code: `scripts/market_bias_walk_forward.py`.
- The generic rule selector now applies the same style of stability filter used in the stronger residual search:
  - recent active-month check,
  - recent ROI must be non-negative,
  - recent positive months must not trail recent negative months,
  - monthly ROI lower-confidence bound must be positive.
- Test: `tests/test_market_bias_walk_forward.py` verifies that a higher total-profit but volatile/recently weak rule is rejected in favor of a lower-profit stable rule.
- I2 draw re-run with the hardened selector:

| Report | Bets | Profit | ROI | Max DD | Active Months | Month Balance | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Previous I2 baseline | 692 | +59.68 | 8.62% | 21.00 | 24 | 14 / 10 | `research_candidate_requires_live_shadow` |
| `market_bias_walk_forward_i2_draw_stability_lcb` | 404 | +17.05 | 4.22% | 19.74 | 12 | 6 / 6 | `candidate_positive_but_unstable` |

Interpretation:

- The hardened selector removes many historical bets and exposes that I2 draw still depends on unstable active windows.
- This is progress in algorithm quality, not in production readiness: the strategy remains positive, but drawdown/profit worsens to `1.158` and month balance is flat.
- Practical decision: keep the LCB/recent-stability selector as the default safety layer for future searches, but do not promote I2 single-rule allocation from this result.

Multi-window stability optimizer:

- Code: `scripts/market_bias_multi_window_optimizer.py`.
- The optimizer now accepts `--diagnostics-csv`, `--top-n`, `--min-diagnostic-sources`, and `--no-include-default-rule`, so it can turn diagnostic CSV rows into walk-forward candidate specs instead of only testing hand-picked candidates.
- It also reports active-window stability separately from calendar-window stability:
  - `pass_rate`: passed windows / all calendar windows,
  - `active_pass_rate`: passed windows / windows with at least one bet,
  - `min_active_windows`: minimum number of active windows required before active-window stability can promote a rule.
- Default candidate re-run with the hardened selector:

| Candidate | Calendar Passed | Active Passed | Source Pass Rate | Bets | Profit | ROI | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `I2 draw` | 3 / 12 | 3 / 9 | 1.00 | 1199 | +308.10 | 2.57% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `I2 draw + SP1 home` | 3 / 12 | 3 / 10 | 1.00 | 1331 | +341.90 | 2.57% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `SP1 home` | 0 / 12 | 0 / 6 | 0.00 | 132 | +33.80 | 2.56% | `REJECT_UNSTABLE` |

- Diagnostic Top8 search:

| Candidate | Calendar Passed | Active Passed | Source Pass Rate | Bets | Profit | ROI | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `T1 market_prob [0.55,1.00]` | 2 / 12 | 2 / 11 | 0.50 | 470 | -52.40 | -1.11% | `REJECT_UNSTABLE` |
| `G1 draw market_prob [0.28,0.34)` | 1 / 12 | 1 / 6 | 0.50 | 152 | +168.20 | 11.07% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `I1 away odds [1.0,1.8)` | 0 / 12 | 0 / 2 | 0.00 | 11 | +0.90 | 0.82% | `REJECT_UNSTABLE` |

Interpretation:

- No candidate reached `MULTI_WINDOW_SHADOW_CANDIDATE`.
- The important find is negative but useful: even rules with attractive aggregate profit, such as `G1 draw market_prob [0.28,0.34)`, fail because too few rolling windows pass. That is exactly the kind of "profitable month, bad algorithm" pattern the project is trying to avoid.
- Next search direction should not relax the window gate. Instead, search broader candidate sets and require stability before considering shadow allocation.

Worldwide multi-source multi-window search:

- Report: `reports/market_bias_multi_window_optimizer_worldwide_multisource_top5_stability_lcb/summary.json`.
- Inputs:
  - diagnostics: worldwide AVG_CLOSE + PS_CLOSE,
  - candidate filter: `--min-diagnostic-sources 2`,
  - validation sources: AVG_CLOSE + PS_CLOSE,
  - seasons: ARG,AUT,BRA,CHN,DNK,FIN,IRL,JPN,MEX,NOR,POL,ROU,RUS,SWE,SWZ,USA,
  - test span: 2013-04..2026-05,
  - rolling windows: 12 months, 6-month step.

| Candidate | Calendar Passed | Active Passed | Source Pass Rate | Bets | Profit | ROI | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `SWE away odds [2.2,2.8)` | 1 / 50 | 1 / 5 | 0.50 | 54 | +116.40 | 21.56% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `JPN away market_prob [0.28,0.34)` | 3 / 50 | 3 / 21 | 1.00 | 380 | +147.60 | 3.88% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `RUS home odds [2.2,2.8)` | 0 / 50 | 0 / 11 | 0.00 | 148 | -143.60 | -9.70% | `REJECT_UNSTABLE` |
| `NOR home odds [1.8,2.2)` | 0 / 50 | 0 / 9 | 0.00 | 144 | -193.80 | -13.46% | `REJECT_UNSTABLE` |
| `AUT away market_prob [0.20,0.28)` | 0 / 50 | 0 / 1 | 0.00 | 3 | -30.00 | -100.00% | `REJECT_UNSTABLE` |

Interpretation:

- No worldwide candidate reached `MULTI_WINDOW_SHADOW_CANDIDATE`.
- JPN remains the best research-watch candidate because it is positive across both validation sources, but 3 / 21 active passing windows is still far below the 60% active pass-rate requirement.
- SWE is a classic small-window trap: high ROI, only 54 total bets, only 1 / 5 active windows passed.
- The stricter conclusion is unchanged: do not promote worldwide market-bias rules until the edge survives many rolling windows, not just aggregate CSV profit.

Worldwide pair-combination search:

- Code: `scripts/market_bias_multi_window_optimizer.py`.
- New option: `--combo-size 2` builds pair candidates from diagnostic TopN rules; `--max-combinations` caps the experiment size.
- Report: `reports/market_bias_multi_window_optimizer_worldwide_combo_top4_pairs_stability_lcb/summary.json`.
- Inputs: worldwide AVG_CLOSE + PS_CLOSE diagnostics, Top4 rules, all 6 pair combinations, same 2013-04..2026-05 rolling-window validation.

| Candidate | Calendar Passed | Active Passed | Source Pass Rate | Bets | Profit | ROI | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `JPN away market_prob + SWE away odds` | 4 / 50 | 4 / 22 | 1.00 | 434 | +264.00 | 6.08% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `RUS home odds + JPN away market_prob` | 3 / 50 | 3 / 26 | 0.50 | 528 | +4.00 | 0.08% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `JPN away market_prob + NOR home odds` | 3 / 50 | 3 / 26 | 0.50 | 524 | -46.20 | -0.88% | `REJECT_UNSTABLE` |
| `RUS home odds + SWE away odds` | 2 / 50 | 2 / 12 | 0.50 | 202 | -27.20 | -1.35% | `REJECT_UNSTABLE` |

Interpretation:

- Pairing rules improves aggregate return for the best case: JPN + SWE rises to 6.08% ROI and stays positive on both validation sources.
- It still fails stability: active pass rate is only 4 / 22 = 18.18%, far below the 60% promotion gate.
- The optimizer now writes `unit_bets.csv` and per-window `rule_contributions`, so pair results can be decomposed by rule.
- JPN + SWE contribution diagnosis:
  - JPN away: 380 repeated-window bets, +147.60 profit, 3.88% ROI, 21 active windows.
  - SWE away: 54 repeated-window bets, +116.40 profit, 21.56% ROI, 5 active windows.
- JPN AVG_CLOSE is weak: 200 bets, +11.80 profit, 0.59% ROI.
- SWE is high-return but sparse: only 5 active windows across both sources.
- Simple diversification is therefore not enough. The best pair is still driven by sparse SWE profit plus weak JPN baseline exposure. The next algorithmic direction should add portfolio-level risk/correlation selection or dynamic exposure control, not just combine high-ROI rules.

Rule-level dynamic exposure control:

- Code: `scripts/rule_exposure_control.py`.
- Report: `reports/rule_exposure_control_jpn_swe_l20_min8_cd30/summary.json`.
- Baseline report: `reports/rule_exposure_control_jpn_swe_static_baseline/summary.json`.
- Rule gate:
  - use only settled results,
  - look back over the latest 20 settled bets for each rule,
  - require at least 8 settled samples,
  - if recent rule profit is below 0, pause that rule for 30 days.

| Strategy | Bets | Profit | ROI | Max DD | Active Months | Month Balance | Active Window Pass |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Static JPN + SWE | 217 | +132.00 | 6.08% | 198.10 | 22 | 14 / 8 | 3 / 12 |
| Rule cooldown JPN + SWE | 92 | +118.10 | 12.84% | 112.30 | 22 | 13 / 9 | 2 / 12 |

Interpretation:

- Rule-level cooldown improves capital efficiency: fewer bets, higher ROI, lower absolute drawdown.
- It does not improve multi-window stability. Active-window pass rate falls from 3 / 12 to 2 / 12.
- Current decision: keep rule-level exposure control as a risk-management tool, but do not treat it as the profitable algorithm. It makes a weak candidate less painful; it does not make the edge stable enough.

Rule exposure parameter grid:

- Code: `scripts/rule_exposure_grid_search.py`.
- Report: `reports/rule_exposure_grid_search_jpn_swe/summary.json`.
- Grid:
  - lookback settlements: 10, 20, 30,
  - minimum settled samples: 4, 8, 12,
  - cooldown days: 14, 30, 60.

Best row:

| Lookback | Min Samples | Cooldown | Bets | Profit | ROI | Max DD | DD / Profit | Month Balance | Active Window Pass |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 10 | 8 | 14 | 114 | +176.00 | 15.44% | 66.80 | 0.3795 | 15 / 7 | 5 / 12 |

Interpretation:

- Parameter search materially improves the dynamic exposure result: active-window pass rate rises from 2 / 12 to 5 / 12, ROI rises to 15.44%, and drawdown/profit improves to 0.3795.
- It still does not satisfy the 60% active-window promotion gate: 5 / 12 = 41.67%.
- Current status: strongest research candidate so far, but still below the required multi-month stability threshold. Keep it as `BEST_RESEARCH_CANDIDATE_NOT_PROMOTED`.

Multi-source candidate screen:

- `scripts/market_bias_candidate_screen.py` now accepts multiple `--diagnostics-csv` inputs and `--min-diagnostic-sources`.
- This is a stricter discovery step: a rule must appear in multiple diagnostic sources before it is tested through no-lookahead walk-forward and settlement-aware portfolio simulation.
- `--no-include-default-rule` disables the I2 baseline when screening unrelated data domains, so worldwide experiments are not polluted by a European baseline rule.
- The same script now accepts multiple `--validation-odds-source` values and writes `rule_summary`, so a candidate can be judged by cross-source validation in one report instead of manually comparing separate runs.

Worldwide multi-source screen command pattern:

- AVG close validation:
  `python scripts/market_bias_candidate_screen.py --diagnostics-csv reports/market_bias_diagnostics_worldwide_avg_close/market_bias.csv --diagnostics-csv reports/market_bias_diagnostics_worldwide_ps_close/market_bias.csv --min-diagnostic-sources 2 --no-include-default-rule --seasons ARG,AUT,BRA,CHN,DNK,FIN,IRL,JPN,MEX,NOR,POL,ROU,RUS,SWE,SWZ,USA --first-month 2013-04 --last-month 2026-05 --odds-source AVG_CLOSE --output-dir reports/market_bias_candidate_screen_worldwide_multisource_avg_close`
- PS close validation:
  `python scripts/market_bias_candidate_screen.py --diagnostics-csv reports/market_bias_diagnostics_worldwide_avg_close/market_bias.csv --diagnostics-csv reports/market_bias_diagnostics_worldwide_ps_close/market_bias.csv --min-diagnostic-sources 2 --no-include-default-rule --seasons ARG,AUT,BRA,CHN,DNK,FIN,IRL,JPN,MEX,NOR,POL,ROU,RUS,SWE,SWZ,USA --first-month 2013-04 --last-month 2026-05 --odds-source PS_CLOSE --output-dir reports/market_bias_candidate_screen_worldwide_multisource_ps_close`
- Cross-source validation in one run:
  `python scripts/market_bias_candidate_screen.py --diagnostics-csv reports/market_bias_diagnostics_worldwide_avg_close/market_bias.csv --diagnostics-csv reports/market_bias_diagnostics_worldwide_ps_close/market_bias.csv --min-diagnostic-sources 2 --no-include-default-rule --seasons ARG,AUT,BRA,CHN,DNK,FIN,IRL,JPN,MEX,NOR,POL,ROU,RUS,SWE,SWZ,USA --first-month 2013-04 --last-month 2026-05 --validation-odds-source AVG_CLOSE --validation-odds-source PS_CLOSE --output-dir reports/market_bias_candidate_screen_worldwide_multisource_cross_validated`

Multi-source screen result:

| Candidate | AVG_CLOSE Portfolio | PS_CLOSE Portfolio | Screen Verdict |
| --- | --- | --- | --- |
| `JPN away / market probability [0.28,0.34)` | 339 bets, +211.40, 6.24% ROI, max DD 165.80 | 402 bets, +192.40, 4.79% ROI, max DD 182.40 | Passes screen; keep research watch only |
| `SWE away / odds [2.2,2.8)` | 60 bets, +121.90, 20.32% ROI | 9 bets, +35.90, 39.89% ROI | Reject: too few bets |
| `AUT away / market probability [0.20,0.28)` | 42 bets, +62.80, 14.95% ROI | 18 bets, +53.60, 29.78% ROI | Reject: too few bets |
| `RUS home / odds [2.2,2.8)` | 122 bets, +48.20, 3.95% ROI, max DD 96.50 | 164 bets, +19.00, 1.16% ROI, max DD 123.40 | Reject: drawdown/source weakness |
| `NOR home / odds [1.8,2.2)` | 206 bets, +124.60, 6.05% ROI, max DD 169.90 | 161 bets, -95.90, -5.96% ROI | Reject: cross-source failure |

Interpretation:

- The automated multi-source screen agrees with the manual review: JPN is the only worldwide candidate worth monitoring next.
- Cross-source aggregate for JPN: 741 combined validation bets, +403.80 profit, 5.45% combined ROI, 4.79% worst-source ROI, passed 2 / 2 validation sources.
- It also catches seductive but weak candidates: SWE/AUT have eye-catching ROI but collapse on sample size; RUS/NOR fail stability or cross-source behavior.
- This strengthens the process, not the production decision. JPN still remains below full promotion quality because the robustness gate is only `4 / 12` and official Chinese SP prospective validation is missing.

JPN research package:

- Command:
  `python scripts/market_bias_research_candidate_package.py --strategy-id research-market-bias-jpn-away-market-prob-0.28-0.34-v1 --rule "league|outcome|market_prob_bucket=JPN|away|[0.28,0.34)" --robustness reports/market_bias_robustness_gate_worldwide_jpn_away_prob28_34/summary.json --portfolio reports/market_bias_portfolio_simulation_worldwide_jpn_away_prob28_34_avg_close/summary.json --candidate-screen reports/market_bias_candidate_screen_worldwide_multisource_cross_validated/summary.json --output reports/market_bias_research_candidate_jpn_away_prob28_34/summary.json`
- Classification: `RESEARCH_WATCH_ONLY`.
- Promotion decision: `REJECT_RESEARCH_CANDIDATE`.
- It passes the candidate screen and portfolio checks, but fails promotion blocking checks:
  `robust_decision`, `robust_pass_rate`, and `source_passes`.
- Official-SP production checks also fail because there are no prospective Chinese official-SP samples:
  `official_sample`, `official_months`, `official_roi`, and `official_month_balance`.
- Practical conclusion: JPN is useful for monitoring and future data collection, but it must not create shadow picks or production betting recommendations yet.

JPN profit scorecard:

- Report: `reports/market_bias_profit_algorithm_scorecard_jpn_away_prob28_34/summary.json`.
- Score: `62.98 / 100`.
- Deployment tier: `RESEARCH_WATCH_ONLY`.
- It scores well on settlement portfolio and cross-source validation, but historical robustness is only `15.33 / 30` and official-SP prospective evidence is `0 / 20`.
- This is intentionally stricter than "profitable in historical CSV": it keeps the rule visible for research while blocking shadow picks and real betting until source diversity and official-SP validation improve.

Low-correlation rule combination search:

- Code:
  - `scripts/build_rule_unit_bets_from_market_candidates.py`.
  - `scripts/low_correlation_rule_combo_search.py`.
- Top-20 diagnostic rule pool:
  - Unit bets: `reports/direct_rule_unit_bets_worldwide_top20_v1/unit_bets.csv`.
  - Search report: `reports/low_correlation_rule_combo_search_worldwide_top20_combo3_v1/summary.json`.
  - Split check: `reports/low_correlation_rule_combo_search_worldwide_top20_combo3_v1/split_check.json`.
- Cross-source stricter rule pool:
  - Unit bets: `reports/direct_rule_unit_bets_worldwide_cross_source_top12_v1/unit_bets.csv`.
  - Search report: `reports/low_correlation_rule_combo_search_worldwide_cross_source_top12_combo3_v1/summary.json`.

Best top-20 three-rule combo:

| Rule Set | Bets | Profit | ROI | Monthly Corr Max | Month Balance | Active Window Pass |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `PS_CLOSE JPN away odds [2.8,3.5)` + `PS_CLOSE AUT away odds [1.8,2.2)` + `PS_CLOSE NOR odds [2.2,2.8) / prob [0.42,0.55)` | 1652 | +123.03 | 7.45% | 0.0335 | 88 / 60 | 17 / 25 |

Split check for the same combo:

| Period | Bets | Profit | ROI | Month Balance | Active Window Pass |
| --- | ---: | ---: | ---: | --- | --- |
| 2013-04..2021-12 | 966 | +90.38 | 9.36% | 58 / 35 | 11 / 16 |
| 2022-01..2026-05 | 556 | +44.88 | 8.07% | 26 / 17 | 5 / 7 |
| 2024-01..2026-05 | 304 | +46.36 | 15.25% | 14 / 8 | 2 / 3 |

Best stricter cross-source three-rule combo:

| Rule Set | Bets | Profit | ROI | Monthly Corr Max | Month Balance | Active Window Pass |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `AVG_CLOSE RUS home odds [2.2,2.8)` + `PS_CLOSE JPN away prob [0.28,0.34)` + `AVG_CLOSE AUT away prob [0.20,0.28)` | 2158 | +151.35 | 7.01% | 0.1141 | 84 / 70 | 15 / 25 |

Interpretation:

- This is the first research path that reaches or exceeds the 60% active-window threshold on a broad historical monthly-window scan.
- The top-20 result is stronger at 17 / 25 = 68%, and the stricter cross-source pool reaches exactly 15 / 25 = 60%.
- However, these are still not production-ready because the diagnostic rule pool was selected from full historical diagnostics. That introduces rule-selection leakage even though the downstream window checks are chronological.
- Current status: `PROMISING_RESEARCH_CANDIDATE_NEEDS_NO_LEAKAGE_ROLLING_SELECTION`.
- Next required algorithm step: rebuild this as a rolling monthly rule-selection process where each validation window can only use rules discovered from data available before that window.

Rolling no-leakage selector check:

- Code: `scripts/rolling_low_correlation_rule_selector.py`.
- Baseline rolling report: `reports/rolling_low_correlation_rule_selector_worldwide_v1/summary.json`.
- Train-stable report: `reports/rolling_low_correlation_rule_selector_worldwide_trainstable_v2/summary.json`.
- Structured-rule report: `reports/rolling_low_correlation_rule_selector_worldwide_structured_v1/summary.json`.
- Protocol:
  - Validation starts at 2017-01.
  - Each decision uses only the previous 48 months of market candidates.
  - Validation windows are 12 months, stepped every 6 months.
  - Rule discovery is recomputed before each validation window.
  - The structured version requires `league + outcome + odds_bucket/market_prob_bucket`.

No-leakage results:

| Version | Rule Filter | Train Internal Stability | Windows | Passed | Profit | ROI | Decision |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| baseline rolling | broad feature combos | no extra gate | 17 | 2 | -162.79 | -6.57% | reject |
| train-stable v2 | broad feature combos | train pass >= 50% | 17 | 2 | -316.96 | -5.83% | reject |
| structured v1 | `league + outcome + price bucket` | train pass >= 50% | 17 | 1 | -99.49 | -4.63% | reject |

Interpretation:

- The earlier low-correlation result does not survive true rolling rule selection.
- The failure mode is rule-selection overfit: rules that look profitable and even internally stable in the training window do not migrate reliably into the next 12 months.
- This is useful negative evidence. It prevents promoting a strategy that only works after seeing the full historical sample.
- Current status changes from `PROMISING_RESEARCH_CANDIDATE_NEEDS_NO_LEAKAGE_ROLLING_SELECTION` to `REJECTED_BY_NO_LEAKAGE_ROLLING_SELECTION`.
- The next algorithm direction should not be more static market-bias rule mining. It should either add causal features that can explain why a rule should persist, or use online model calibration with very conservative exposure until prospective official-SP evidence accumulates.

Online calibrated residual edge check:

- Code: `scripts/online_calibrated_edge_strategy.py`.
- Tests: `tests/test_online_calibrated_edge_strategy.py`.
- Reports:
  - `reports/online_calibrated_edge_strategy_sp2_v1/summary.json`.
  - `reports/online_calibrated_edge_strategy_sp2_loose_v1/summary.json`.
  - `reports/online_calibrated_edge_strategy_all_leagues_v1/summary.json`.
  - `reports/online_calibrated_edge_strategy_cross_league_bucket_v1/summary.json`.
  - `reports/online_calibrated_edge_strategy_cross_league_bucket_loose_v1/summary.json`.
- Protocol:
  - Fit residual probability model from prior months only.
  - Generate candidate edges for the current month without using current results.
  - Before staking, allow only buckets whose prior settled candidate history passes sample, ROI, and month-balance gates.
  - Use unit stake to evaluate edge quality separately from bankroll sizing.

Online calibration results:

| Variant | Bucket Columns | Scope | Bets | Profit | ROI | Month Balance | Decision |
| --- | --- | --- | ---: | ---: | ---: | --- | --- |
| SP2 strict | `league,outcome,odds_bucket` | SP2 only | 5 | +0.50 | 10.00% | 2 / 1 | not enough sample |
| SP2 loose | `league,outcome,odds_bucket` | SP2 only | 20 | +1.76 | 8.80% | 7 / 5 | promising but too small |
| all leagues | `league,outcome,odds_bucket` | all football-data leagues | 23 | -1.95 | -8.48% | 10 / 3 | reject |
| cross-league strict | `outcome,odds_bucket` | all football-data leagues | 48 | -13.62 | -28.38% | 1 / 2 | reject |
| cross-league loose | `outcome,odds_bucket` | all football-data leagues | 183 | -11.58 | -6.33% | 5 / 6 | reject |

Interpretation:

- Online calibration is methodologically better than static rule mining because it only trusts prior settled candidate history.
- The SP2-only result remains directionally positive but has too few bets to prove an algorithm.
- Cross-league bucket sharing increases sample size but loses money, so the SP2 signal does not generalize under the current residual model.
- Current status: `ONLINE_CALIBRATION_RESEARCH_ONLY_INSUFFICIENT_SAMPLE`.
- Practical next step: collect prospective official-SP and closing-snapshot data for the SP2-like residual edge shape, rather than forcing cross-league extrapolation.

League-level online calibration scan:

- Code: `scripts/online_calibration_league_scan.py`.
- Tests: `tests/test_online_calibration_league_scan.py`.
- Loose scan report: `reports/online_calibration_league_scan_loose_v1/summary.json`.
- Minimum-odds scan report: `reports/online_calibration_league_scan_minodds18_v1/summary.json`.
- Purpose: test whether the SP2 online-calibration signal is isolated or whether similar league-specific signals exist elsewhere.

Loose league scan (`min_odds=1.0`, `min_bets=20`):

| League | Bets | Profit | ROI | Month Balance | Decision | Main Shape |
| --- | ---: | ---: | ---: | --- | --- | --- |
| P1 | 47 | +9.09 | 19.34% | 18 / 3 | `RESEARCH_WATCH` | mostly home/away odds `[1.0,1.8)` |
| I1 | 119 | +5.32 | 4.47% | 21 / 17 | `RESEARCH_WATCH` | mostly home/away odds `[1.0,1.8)` |
| SP1 | 94 | +2.66 | 2.83% | 17 / 15 | `RESEARCH_WATCH` | mostly home/away odds `[1.0,1.8)` |

Minimum-odds scan (`min_odds=1.8`, same gates):

| League | Bets | Profit | ROI | Month Balance | Decision |
| --- | ---: | ---: | ---: | --- | --- |
| I2 | 21 | +5.63 | 26.81% | 5 / 7 | `REJECT_MONTH_BALANCE` |
| SP2 | 20 | +1.76 | 8.80% | 7 / 5 | `REJECT_DRAWDOWN` |
| all others | < 20 or <= 0 profit | n/a | n/a | n/a | reject / too few bets |

Interpretation:

- League-level scan finds some positive online-calibrated results, but the robust-looking ones mostly come from very low odds `[1.0,1.8)` favorites.
- Excluding low odds clears the watchlist. This weakens the practical money-making case because low-odds edges are most vulnerable to commission, stale prices, stake limits, and small pricing error.
- SP2 remains the most interesting non-low-odds signal, but with only 20 bets and drawdown larger than profit it is still not a viable algorithm.
- Current status: `NO_CONFIRMED_ONLINE_CALIBRATED_EDGE_AFTER_LOW_ODDS_FILTER`.

Online CLV-filtered residual edge check:

- Code: `scripts/online_clv_filtered_edge_strategy.py`.
- Tests: `tests/test_online_clv_filtered_edge_strategy.py`.
- Reports:
  - `reports/online_clv_filtered_edge_strategy_all_minodds18_v2/summary.json`.
  - `reports/online_clv_filtered_edge_strategy_sp2_minodds18_v1/summary.json`.
  - `reports/online_clv_filtered_edge_strategy_crossleague_minodds18_clvonly_v2/summary.json`.
  - `reports/online_clv_filtered_edge_strategy_crossleague_minodds18_relaxed_v1/summary.json`.
  - `reports/online_clv_filtered_edge_strategy_all_minodds18_relaxed_v1/summary.json`.
- Protocol:
  - Bet using opening/pre-closing odds only.
  - Attach closing odds only after the match as a reference.
  - Future months may only use prior candidate buckets with acceptable historical CLV / closing-edge behavior.

CLV-filter results:

| Variant | Bucket Columns | Filters | Bets | Profit | ROI | Decision |
| --- | --- | --- | ---: | ---: | ---: | --- |
| all min-odds strict | `league,outcome,odds_bucket` | positive CLV, positive closing edge, positive profit | 1 | -1.00 | -100.00% | reject / too sparse |
| SP2 min-odds strict | `league,outcome,odds_bucket` | positive CLV, positive closing edge, positive profit | 0 | 0.00 | 0.00% | no sample |
| cross-league CLV-only | `outcome,odds_bucket` | positive CLV and closing edge, no profit gate | 1 | +3.00 | 300.00% | too sparse |
| cross-league relaxed | `outcome,odds_bucket` | CLV >= -0.5%, closing edge >= -1% | 1 | +3.00 | 300.00% | too sparse |
| league relaxed | `league,outcome,odds_bucket` | CLV >= -0.5%, closing edge >= -1% | 14 | -10.18 | -72.71% | reject |

Interpretation:

- The current residual candidates do sometimes show positive average CLV, but this does not convert into stable betting profit.
- Most broad buckets have positive CLV but negative closing-edge estimates, which means the odds may shorten without creating true expected value at the original price.
- Strict CLV filters produce almost no bets; relaxed filters create losing samples.
- Current status: `CLV_FILTER_REJECTED_OR_TOO_SPARSE`.
- Practical implication: CLV should remain a diagnostic field in shadow validation, not a standalone promotion signal.

Residual model feature upgrade check:

- Code: `scripts/walk_forward_residual_strategy.py`.
- Added no-leakage team state features:
  - recent points per match delta,
  - recent goals-for / goals-against delta,
  - recent goal-difference delta,
  - season points-per-match delta,
  - season goal-difference-per-match delta,
  - rest-days delta.
- Tests: `tests/test_walk_forward_residual_strategy.py`.
- Reports:
  - `reports/online_calibrated_edge_strategy_sp2_form_features_v1/summary.json`.
  - `reports/online_calibration_league_scan_minodds18_form_features_v1/summary.json`.
  - `reports/online_calibration_league_scan_loose_form_features_v1/summary.json`.

Comparison:

| Variant | Scope | Min Odds | Bets | Profit | ROI | Month Balance | Watchlist |
| --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| prior SP2 loose | SP2 | 1.8 | 20 | +1.76 | 8.80% | 7 / 5 | n/a |
| form-feature SP2 | SP2 | 1.8 | 14 | +0.75 | 5.36% | 5 / 6 | n/a |
| prior league scan | all leagues | 1.8 | n/a | n/a | n/a | n/a | none |
| form-feature league scan | all leagues | 1.8 | n/a | n/a | n/a | n/a | none |
| form-feature loose scan | all leagues | 1.0 | n/a | n/a | n/a | n/a | P1 only |

Interpretation:

- More realistic team-state features did not improve the money-making signal.
- SP2 remains positive but smaller and less stable after the feature upgrade.
- With low odds excluded, no league passes the online calibration watchlist.
- With low odds allowed, P1 returns as a watch candidate, but it is still mostly `[1.0,1.8)` favorite exposure.
- Current status: `FORM_FEATURE_UPGRADE_DID_NOT_CREATE_CONFIRMED_EDGE`.

## Next Research Step

Do not promote the current market-bias rules to live betting yet. The strongest historical-looking path, low-correlation multi-rule market-bias selection, has now failed the no-leakage rolling check. Candidate directions:

- Stop treating static market-bias rule mining as the main path; use it only as diagnostic evidence.
- Shift the main algorithm toward online calibration: compare model probability, market consensus, closing-line movement, and official-SP drift, then update exposure only from settled prospective evidence.
- Run prospective shadow validation for the `I2 + SP1` combo without changing the rules.
- Keep pure `SP1 home / market probability [0.55,1.00]` as a separate high-ROI challenger, but do not treat its small sample as enough for production.
- Compare the I2 rule against Chinese official SP snapshots. If official SP behaves like AVG/MAX open, keep it as a candidate; if it behaves like B365 close or worse, downgrade it.
- Re-run `validate-market-bias-official-sp` after each batch of settled official matches; do not promote before official-SP sample size and month coverage are meaningful.
- Re-run `market_bias_promotion_gate.py` after both official-SP validation and portfolio simulation refresh. Production promotion requires the gate to reach `PRODUCTION_CANDIDATE_REQUIRES_HUMAN_CONFIRMATION`.
- Keep B1 rejected as a primary candidate for now; keep T1 as secondary research until recent-season weakness is better understood.
- Add bankroll simulation with fixed daily limit and settlement delay for the I2 rule.
- Keep `reports/market_bias_walk_forward_single_league_outcome_odds_bucket_I2_draw_2_8_3_5/summary.json` as the current primary research baseline.
- Continue using `reports/training_window_sensitivity_v1/summary.json`, `reports/multi_window_consensus_v1_min2/summary.json`, and `reports/candidate_feature_diagnostics_v1/summary.json` as rejection gates for model-derived candidates.
- Optimize for stability-adjusted return: profit is useful only if monthly balance, season balance, and drawdown survive.
- Keep the monthly validation process frozen before settlement; do not use final match results when choosing same-day bets.

Official market data sufficiency check:

- Code: `scripts/official_market_data_sufficiency.py`.
- Tests: `tests/test_official_market_data_sufficiency.py`.
- Report: `reports/official_market_data_sufficiency/summary.json`.
- Purpose: decide whether the project currently has enough real official-SP, external-market, and settled-result data to run a no-leakage official-vs-external edge algorithm.

Current local database result:

| Metric | Value |
| --- | ---: |
| matches | 61 |
| external_bookmaker_odds | 164 |
| results | 0 |
| official_odds_observations | missing table |
| official_odds_closing_observations | missing view |
| official opening settled matches | unavailable |
| external settled matches | 0 |

Interpretation:

- The next money-making algorithm should be based on official SP versus external market consensus, but the current local database cannot validate it yet.
- This is a hard blocker, not a threshold problem: there are no settled official-SP samples and the official odds time-series objects are missing from the active database.
- Current status: `BLOCKED_SCHEMA_MISSING`.
- Required before the next algorithm experiment:
  - run database initialization/migrations so `official_odds_observations` and `official_odds_closing_observations` exist,
  - collect hourly pre-match official SP snapshots,
  - settle matches into `results` only after public final scores are known,
  - require at least 200 settled official-SP matches across at least 6 months before promoting any official-market edge strategy.

Statistical audit layer:

- Code: `scripts/strategy_statistical_audit.py`.
- Tests: `tests/test_strategy_statistical_audit.py`.
- Integrated into scorecard: `scripts/market_bias_profit_algorithm_scorecard.py`.
- Reports:
  - `reports/strategy_statistical_audit_i2_draw_avg_open/summary.json`.
  - `reports/strategy_statistical_audit_i2_sp1_combo_avg_open/summary.json`.
- Method:
  - Aggregate placed bets by active betting month.
  - Bootstrap months with replacement to estimate ROI/profit confidence intervals.
  - Run a month-level sign-flip test against a zero-edge null.
  - Use the audit as a non-scoring gate: it can block weak candidates, but it does not add extra score.

Current statistical audit results:

| Candidate | Bets | Active Months | ROI | Bootstrap ROI 5% | Positive ROI Probability | Sign-Flip p | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `I2 draw [2.8,3.5)` | 871 | 28 | 9.50% | 1.85% | 98.02% | 0.0314 | `STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE` |
| `I2 draw + SP1 home` | 1037 | 31 | 10.03% | 3.77% | 99.62% | 0.0124 | `STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE` |

Updated interpretation:

- The `I2 draw [2.8,3.5)` strategy still has statistically detectable historical signal, but the refreshed multi-window gate now rejects it for deployment. A statistically positive full-period sample is not enough when rolling windows are unstable.
- The `I2 draw + SP1 home` combo has stronger bootstrap statistics and higher ROI, but also fails the refreshed multi-window gate. It remains research-only rather than shadow-ready.
- Current best historical deployment tier:
  - `I2 draw [2.8,3.5)`: `RESEARCH_ONLY_UNSTABLE_WINDOWS`.
  - `I2 draw + SP1 home`: `RESEARCH_ONLY_UNSTABLE_WINDOWS`.
- Production betting is blocked first by multi-window instability and then by missing official-SP prospective evidence.

Selected-odds edge calibration layer:

- Code: `scripts/strategy_edge_calibration.py`.
- Tests: `tests/test_strategy_edge_calibration.py`.
- Integrated into scorecard: `scripts/market_bias_profit_algorithm_scorecard.py`.
- Reports:
  - `reports/strategy_edge_calibration_i2_draw_avg_open/summary.json`.
  - `reports/strategy_edge_calibration_i2_sp1_combo_avg_open/summary.json`.
- Method:
  - Compare actual hit rate with `mean(1 / selected_decimal_odds)`.
  - Use a Wilson 95% lower bound for the observed hit rate.
  - Confirm an edge only when the lower bound still exceeds the selected-side implied probability.

Calibration results:

| Candidate | Bets | Hit Rate | Wilson 95% Lower | Avg Implied Probability | Edge | Conservative Edge | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `I2 draw [2.8,3.5)` | 871 | 34.79% | 31.70% | 31.74% | +3.05pp | -0.04pp | `POSITIVE_EDGE_BUT_NOT_CONSERVATIVE` |
| `I2 draw + SP1 home` | 1037 | 41.66% | 38.69% | 37.79% | +3.87pp | +0.91pp | `CALIBRATED_EDGE_CONFIRMED` |

Updated stricter conclusion:

- `I2 draw [2.8,3.5)` has statistically detectable full-period signal, but the refreshed multi-window gate now rejects it for deployment. It remains `RESEARCH_ONLY_UNSTABLE_WINDOWS`, not a live allocation rule.
- `I2 draw + SP1 home` passes monthly statistical audit and selected-odds calibration, but still fails the multi-window gate (`7 / 12`, `58.33%` versus the `60%` requirement). It remains `RESEARCH_ONLY_UNSTABLE_WINDOWS`.
- Therefore the project has not yet found a fully promotable historical betting algorithm under the stricter requirements.
- The practical research target is now clear:
  - improve `I2 + SP1` multi-window stability without weakening the gate, or
  - improve the `I2 draw` rule's conservative calibration margin without sacrificing its multi-window pass rate.

I2 band stability scan:

- Code: `scripts/i2_sp1_band_stability_scan.py`.
- Tests: `tests/test_i2_sp1_band_stability_scan.py`.
- Report: `reports/i2_sp1_band_stability_scan_focused_v1/summary.json`.
- Purpose: test whether the `I2 draw + SP1 home` candidate can be stabilized by changing only the I2 draw odds band while keeping the SP1 leg fixed.
- Scan grid:
  - I2 draw lower bounds: `2.80`, `2.90`, `3.00`, `3.10`.
  - I2 draw upper bounds: `3.30`, `3.40`, `3.50`.
  - Sources: `AVG_OPEN`, `AVG_CLOSE`.

Top focused scan results:

| Candidate | Passed Windows | Pass Rate | Bets | Combined ROI | Worst Window ROI | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `I2 draw [2.80,3.50) + SP1 home` | 3 / 12 | 25.00% | 1331 | 2.57% | -18.42% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `I2 draw [2.80,3.30) + SP1 home` | 3 / 12 | 25.00% | 980 | 2.06% | -18.42% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `I2 draw [2.80,3.40) + SP1 home` | 2 / 12 | 16.67% | 1102 | 2.40% | -18.42% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `I2 draw [3.00,3.50) + SP1 home` | 1 / 12 | 8.33% | 700 | 0.44% | -26.67% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |

Interpretation:

- Simple I2 odds-band tightening does not solve the `I2 + SP1` multi-window problem.
- Raising the lower bound reduces sample size and generally worsens source stability, especially on `AVG_CLOSE`.
- The next algorithmic direction should not be more static I2 band tuning. It should test dynamic rule activation based only on prior settled rule state, for example: enable/disable a leg when its trailing calibration, drawdown, or month balance deteriorates.

Monthly dynamic rule activation:

- Code: `scripts/monthly_rule_activation_strategy.py`.
- Tests: `tests/test_monthly_rule_activation_strategy.py`.
- Reports:
  - `reports/monthly_rule_activation_i2_sp1_v1/summary.json`.
  - `reports/strategy_statistical_audit_monthly_activation_i2_sp1_v1/summary.json`.
  - `reports/strategy_edge_calibration_monthly_activation_i2_sp1_v1/summary.json`.
- Protocol:
  - Generate the same no-lookahead I2 draw + SP1 home candidate stream.
  - At the start of each month, enable or disable each rule leg using only prior months' shadow-observed rule results.
  - Current-month results are not allowed to affect current-month activation.
  - Grid over trailing lookback months, minimum history bets, trailing ROI threshold, and positive-month edge threshold.

Best dynamic activation result:

| Config | Bets | Profit | ROI | Max DD | Positive / Negative Months | Passed Windows | Active Pass Rate |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `lb6_bets20_roineg0p02_edge0_enabled` | 519 | +195.05 | 4.20% | 245.08 | 6 / 7 | 1 / 6 | 20.00% |

Audit of best dynamic activation:

| Audit | Result |
| --- | --- |
| Monthly bootstrap ROI 5% | -6.04% |
| Positive ROI probability | 74.20% |
| Sign-flip p-value | 0.2792 |
| Edge calibration | `POSITIVE_EDGE_BUT_NOT_CONSERVATIVE` |
| Conservative edge vs implied | -2.86pp |

Interpretation:

- Simple trailing monthly rule activation does not solve the stability problem.
- It reduces exposure and nominal ROI versus the static `I2 + SP1` candidate, but does not reduce drawdown enough and fails both statistical audit and conservative calibration.
- This path is rejected as `REJECT_DYNAMIC_TRAILING_RULE_CONTROL`.
- The next useful research step should move below static rule labels:
  - either improve price-source realism and official-SP collection,
  - or build a per-match probability/price-quality model that explains when `I2 draw` or `SP1 home` has real edge, rather than switching whole rule legs on/off from trailing PnL.

Per-bet prior price-quality filtering:

- Code: `scripts/per_bet_price_quality_filter.py`.
- Tests: `tests/test_per_bet_price_quality_filter.py`.
- Reports:
  - `reports/per_bet_price_quality_i2_sp1_v1/summary.json`.
  - `reports/strategy_statistical_audit_per_bet_quality_i2_sp1_v1/summary.json`.
  - `reports/strategy_edge_calibration_per_bet_quality_i2_sp1_v1/summary.json`.
- Protocol:
  - Start from the same no-lookahead `I2 draw + SP1 home` candidate stream.
  - At the start of each month, evaluate each candidate bet against prior-month historical buckets only.
  - Tested bucket keys include:
    - `rule_label + odds_source`,
    - `rule_label + odds_source + market_prob_bucket`.
  - Filters require trailing ROI, hit-rate edge over implied probability, and conservative edge thresholds.

Best per-bet filter result:

| Config | Bets | Profit | ROI | Max DD | Positive / Negative Months | Passed Windows | Active Pass Rate |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| `rule_label+odds_source+market_prob_bucket / lb6 / n20 / roi>=-2% / edge>=-1% / cedge>=-2%` | 239 | +76.58 | 3.33% | 234.00 | 8 / 7 | 1 / 6 | 20.00% |

Audit of best per-bet filter:

| Audit | Result |
| --- | --- |
| Monthly bootstrap ROI 5% | -10.73% |
| Positive ROI probability | 64.24% |
| Sign-flip p-value | 0.3706 |
| Edge calibration | `POSITIVE_EDGE_BUT_NOT_CONSERVATIVE` |
| Conservative edge vs implied | -4.40pp |

Interpretation:

- Historical bucket-level price-quality filtering does not create a stable algorithm.
- The best filter keeps too few bets, leaves high drawdown relative to profit, and fails both bootstrap and conservative calibration.
- This path is rejected as `REJECT_PER_BET_BUCKET_QUALITY_FILTER`.
- The failure is informative: the available categorical market-bias fields are not rich enough to separate true edge from noisy historical buckets. Further progress likely requires either:
  - better real official-SP/closing-price data,
  - richer no-leak team and match context features,
  - or a calibrated probability model evaluated against the actual obtainable price, not just rule/bucket history.

Market-anchored feature residual candidate:

- Code: `scripts/feature_enriched_candidate_filter.py`.
- Strategy package registry: `football_agents/profit_strategy_registry.py`.
- CLI:
  - `python -m football_agents.cli profit-strategies`
  - writes the current package to `reports/profit_strategy_packages/summary.json` when `--output` is provided.
- Tests: `tests/test_feature_enriched_candidate_filter.py`.
- Main reports:
  - `reports/feature_enriched_market_anchored_i2_formal_v1/summary.json`.
  - `reports/feature_enriched_market_anchored_i2_stop3_cool3_v1/summary.json`.
  - `reports/feature_enriched_market_anchored_i2_scorer_v1/scorer.json`.
  - `reports/feature_enriched_market_anchored_i2_avg_close_scorer_v1/scorer.json`.
  - `reports/strategy_statistical_audit_market_anchored_i2_stop3_cool3_v1/summary.json`.
  - `reports/strategy_edge_calibration_market_anchored_i2_stop3_cool3_v1/summary.json`.
- Protocol:
  - Fixed candidate leg: Italy Serie B (`I2`) draw, average opening odds in `[2.8,3.5)`.
  - Monthly walk-forward, trained only on prior candidate rows.
  - Features are no-leak pre-match team and league context from `build_feature_history`, including prior league draw rate, recent form deltas, season strength deltas, rest-day delta, and simple goal-intensity proxies.
  - Model is anchored to market probability: it predicts only a bounded residual over the market-implied probability, with residual cap `0.08`.
  - Selection uses `predicted_ev >= 2%`, at most one selected I2 draw per match day.
  - Risk control uses only settled information: after 3 consecutive losing settlement days, pause for 3 days.

Best current candidate:

| Candidate | Bets | Profit | ROI | Max DD | Positive / Negative Months | Passed Windows | Audit | Calibration |
| --- | ---: | ---: | ---: | ---: | --- | ---: | --- | --- |
| `AVG_OPEN_rulesi2_train30_n120_ev0p02_top1_ridge10_cap0.08 + stop3/cool3` | 303 | +644.10 | 21.26% | 90.00 | 25 / 15 | 5 / 6 | `STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE` | `CALIBRATED_EDGE_CONFIRMED` |

Audit details:

| Check | Result |
| --- | --- |
| Bootstrap ROI 5% | +8.91% |
| Probability ROI positive | 99.75% |
| Sign-flip p-value | 0.0065 |
| Hit rate | 37.95% |
| Avg implied probability | 31.19% |
| Wilson lower hit rate | 32.67% |
| Conservative edge vs implied | +1.48pp |

Interpretation:

- This is the first candidate in this research log that clears the main research gates at the same time:
  - positive out-of-sample profitability,
  - monthly bootstrap support,
  - sign-flip support,
  - selected-odds calibration,
  - and majority rolling-year stability.
- The strategy is not “all NO_BET”; it selects 303 historical bets over 40 active months, while still abstaining on weak days.
- The strongest signal is not broad favorite/underdog betting. It is a narrow, market-anchored Italy Serie B draw edge where the model is allowed only a small residual correction over market probability.
- The first rolling window (`2022-08` to `2023-07`) still fails the window gate, so this should be treated as `PROMOTE_TO_SHADOW_VALIDATION`, not as production-proven live staking.
- The validation source is still football-data average opening odds, not verified China Sports Lottery official SP. Before real-money use, this candidate must be replayed on collected official-SP snapshots with the same no-leak timing.
- Frozen scorer artifacts have been exported for prediction month `2026-06`. The default live validation artifact is configured by `PROFIT_SCORER_ARTIFACT_PATH` and now points to `reports/feature_enriched_market_anchored_i2_avg_close_scorer_v1/scorer.json`.
- The strategy has therefore been registered as `profit-i2-draw-market-anchored-stop3-cool3-v1` with status `PROMOTE_TO_OFFICIAL_SP_SHADOW_VALIDATION`, not `PRODUCTION_READY`.

Official-pool scorer readiness diagnostic:

- Code: `football_agents/profit_scorer_official.py`.
- CLI:
  - `python -m football_agents.cli diagnose-profit-scorer-official-pool --limit 500 --output reports/profit_scorer_official_pool/summary.json`
- Default scorer: `PROFIT_SCORER_ARTIFACT_PATH`, currently `reports/feature_enriched_market_anchored_i2_avg_close_scorer_v1/scorer.json`.
- Purpose: map the current official match pool into the frozen scorer schema and report whether each match can be scored. This command does not create recommendations or bets.
- Current local report: `reports/profit_scorer_official_pool/summary.json`.
- Automation:
  - Background task: `profit_scorer_official_pool_diagnosis`.
  - Runs once on service startup and then every `BACKGROUND_AGENT_INTERVAL_SECONDS`.
  - Writes `PROFIT_SCORER_OFFICIAL_POOL_REPORT_PATH`, defaulting to `reports/profit_scorer_official_pool/summary.json`.

Current official-pool result:

| Check | Value |
| --- | ---: |
| Scanned official matches | 100 |
| Scored by frozen scorer | 0 |
| Passed scorer | 0 |
| `league_not_i2` blockers | 100 |
| `draw_sp_outside_[2.8,3.5)` blockers | 84 |
| `invalid_three_way_official_sp` blockers | 55 |
| Missing live feature blockers | 14 |

Interpretation:

- The current official pool cannot validate this scorer yet. The blocker is not a late EV threshold decision; it happens before scoring.
- The frozen candidate is intentionally narrow: Italy Serie B draw with official draw SP inside `[2.8,3.5)`, complete 1X2 official odds, and live feature rows that can be mapped into the research schema.
- Current official fixtures are mostly outside the validated league/rule domain, and some otherwise scannable rows still lack valid 1X2 SP or model feature fields.
- The live mapping is deliberately conservative. If any required field is missing, the scorer refuses to invent a probability. This prevents false confidence and avoids turning a historically profitable research artifact into fake live recommendations.
- Next algorithm work should improve the official/live feature pipeline and collect prospective official-SP samples for matching I2 fixtures. If the official pool rarely contains I2, a second candidate must pass the same statistical, calibration, and official-SP readiness gates before it can become a real allocation algorithm.

Official-SP prospective validation for the frozen profit scorer:

- Code: `football_agents/profit_scorer_prospective.py`.
- CLI:
  - `python -m football_agents.cli validate-profit-scorer-official-sp --output reports/profit_scorer_official_sp_validation/summary.json`
- Default scorer: `PROFIT_SCORER_ARTIFACT_PATH`, currently `reports/feature_enriched_market_anchored_i2_avg_close_scorer_v1/scorer.json`.
- Tests: `tests/test_profit_scorer_prospective.py`.
- Report: `reports/profit_scorer_official_sp_validation/summary.json`.
- Automation:
  - Background task: `profit_scorer_official_sp_validation`.
  - Runs once on service startup and then every `BACKGROUND_AGENT_INTERVAL_SECONDS`.
  - Writes `PROFIT_SCORER_OFFICIAL_SP_VALIDATION_REPORT_PATH`, defaulting to `reports/profit_scorer_official_sp_validation/summary.json`.
  - Status is exposed in `/health.profitScorerOfficialSp` and recent task runs.
- Protocol:
  - Use only the earliest pre-match official SP snapshot for each match.
  - Run the frozen scorer before settlement.
  - Use match result only after settlement to compute profit.
  - Do not create recommendations or real bets.

Current local result:

| Metric | Value |
| --- | ---: |
| Opening pre-match official SP snapshots | 28 |
| Valid 1X2 snapshots | 28 |
| Settled opening snapshots | 13 |
| Scored by frozen I2 scorer | 0 |
| Selected by scorer | 0 |
| Settled selected samples | 0 |

Current blockers:

| Blocker | Snapshots |
| --- | ---: |
| `league_not_i2` | 28 |
| `draw_sp_outside_[2.8,3.5)` | 19 |

Interpretation:

- The production blocker is now directly measured on the prospective official-SP path.
- The scorer has not failed because of a high EV threshold; it has no eligible official-SP I2 samples yet.
- The rule must remain `PROMOTE_TO_OFFICIAL_SP_SHADOW_VALIDATION`, not production.
- Promotion requires settled selected samples from the same pre-match official-SP path, across multiple months, before any real daily allocation can be justified.

Official-pool-driven research planner:

- Code: `football_agents/official_pool_research.py`.
- CLI:
  - `python -m football_agents.cli plan-official-pool-profit-research --output reports/official_pool_profit_research/summary.json`
- Purpose: make the next algorithm experiment depend on the actual official pool, while preserving the no-fake-edge guardrail.

Current local planner result:

| League | Matches | With latest odds | Mapped code | Evidence status | Research priority |
| --- | ---: | ---: | --- | --- | --- |
| World Cup | 74 | 33 | `WORLD_CUP` | rejected by World Cup tournament holdout | `LOW_DO_NOT_LOOSEN` |
| Finnish Veikkausliiga | 24 | 12 | `FIN` | rejected by existing market-bias and residual tests | `LOW_DO_NOT_LOOSEN` |
| International | 2 | 0 | `INTERNATIONAL` | missing historical 1X2 odds | `DATA_FIRST` |

Interpretation:

- The live pool coverage problem is now explicit and machine-readable.
- World Cup odds are now archived from Footiqo's World Cup database, which describes the odds as historical World Cup closing odds sourced from 1xBet.
- Archived World Cup output: `data/historical_csv/football-data/new/WORLD_CUP.csv`, 128 matched rows, 2018-06-14 through 2022-12-18, 0 dropped rows.
- World Cup market-bias discovery found visually attractive long-shot buckets, but the no-lookahead tournament holdout rejected the reusable allocation rule search. The dataset has only two archived tournaments, so it cannot satisfy the multi-month stability standard.
- International matches still cannot become an odds-edge strategy from results alone. They need historical 1X2 prices captured before kickoff.
- FIN has `5240` historical odds rows locally, but the existing market-bias and residual experiments failed stability gates. That makes FIN a bad candidate for threshold loosening.
- The planner now treats World Cup as `LOW_DO_NOT_LOOSEN` once the rejection report exists. The next algorithmic action is to collect broader paid international 1X2 odds history before retrying an international allocation rule.

World Cup tournament holdout validation:

- Code: `scripts/world_cup_tournament_validation.py`.
- Tests: `tests/test_world_cup_tournament_validation.py`.
- Reports:
  - `reports/world_cup_tournament_validation_current/summary.json`.
  - `reports/world_cup_tournament_validation/summary.json`.
- Protocol:
  - Discover candidate rules only on the 2018 World Cup.
  - Test the discovered rules on the 2022 World Cup.
  - Treat the result as a rejection/triage tool, not as a production promotion path, because only two World Cup tournaments are archived.

Current result:

| Check | Value |
| --- | ---: |
| 2018 train matches | 64 |
| 2022 test matches | 64 |
| Candidate rules tested | 12 |
| Rules passing holdout gate | 0 |
| Decision | `REJECT_NO_REUSABLE_WORLD_CUP_RULE` |
| Promotion decision | `BLOCK_PRODUCTION_WORLD_CUP_SAMPLE_TOO_SMALL` |

Interpretation:

- The strongest 2018-discovered rule family, odds bucket `[4.0,5.0)` with market probability `[0.20,0.28)`, was only mildly profitable in 2022 (`25` bets, `+1.52`, `6.08%` ROI) but failed because positive and negative months were tied and drawdown (`7.70`) exceeded profit.
- Several other 2018-positive rules turned negative in 2022, including away favorites `[1.0,1.8)` and draw `[4.0,5.0)`.
- This rejects the current World Cup market-bias direction as a reusable allocation algorithm.
- World Cup data remains useful for feature enrichment and sanity checks, but it should not be used to justify daily betting allocation until more tournament years or broader paid international odds history are available.

Official-pool-driven market-anchored expansion:

- Code: `scripts/official_pool_market_anchored_research.py`.
- Tests: `tests/test_official_pool_market_anchored_research.py`.
- Reports:
  - `reports/official_pool_market_anchored_research_fin_avg_close/summary.json`.
  - `reports/official_pool_market_anchored_research_world_cup_avg_close/summary.json`.
- Purpose:
  - Take the richer market-anchored residual method that worked best for I2 draw.
  - Apply it only to leagues/rule families relevant to the current official pool.
  - Keep the same monthly no-lookahead protocol and reject candidates that are merely profitable in a narrow slice.

FIN expansion result:

| Best FIN candidate | Bets | Profit | ROI | Positive / Negative Months | Passed Windows | Decision |
| --- | ---: | ---: | ---: | --- | ---: | --- |
| `FIN_home_prob0p55_1p00`, AVG close, train30, EV >= 0 | 112 | +66.00 | 5.89% | 22 / 17 | 3 / 11 | `REJECT_RESEARCH_GATES` |

FIN interpretation:

- The richer model improves some FIN slices versus simple market-bias tests, but it still fails the research gates.
- The best FIN candidate has fewer than 150 bets and only `27.27%` active rolling-window pass rate.
- Other high-ROI FIN away candidates are even smaller and often have drawdown larger than profit.
- This confirms the earlier guardrail: FIN should not be rescued by threshold loosening or by selecting the most attractive profitable sub-slice.

World Cup expansion result:

- The market-anchored residual model selected `0` bets under the configured no-lookahead gates.
- Candidate pools are too small (`29` to `47` rows for the tested World Cup long-shot specs), so the model cannot train responsibly.
- This independently confirms the tournament holdout result: World Cup is not a current allocation algorithm source.

Updated expansion conclusion:

- The market-anchored residual architecture is still useful, but its success has not generalized to FIN or World Cup under the current official-pool-driven specs.
- The current best algorithm remains `profit-i2-draw-market-anchored-stop3-cool3-v1`, still blocked from production by official-SP prospective validation.
- The next useful expansion should require either a larger validated league domain or paid/broader historical international odds; it should not lower stability gates to force daily bets.

Cross-league candidate screener:

- Code: `scripts/market_anchored_candidate_screener.py`.
- Tests: `tests/test_market_anchored_candidate_screener.py`.
- Reports:
  - `reports/market_anchored_candidate_screener_top4_avg_open/summary.json`.
  - `reports/market_anchored_candidate_screener_top4_avg_close/summary.json`.
- Purpose:
  - Take the highest-scoring market-bias discovery rows.
  - Re-test them with the same no-lookahead market-anchored residual model family.
  - Use rolling monthly windows as the stability gate instead of accepting a profitable aggregate backtest.

Implementation note:

- Candidate rule IDs are now stable short hashes, so different rules do not overwrite each other's artifacts when `FeatureFilterConfig.label` is built.
- The screener now builds the market frame and feature history once per run, then filters rules from that shared frame.

Top-4 discovery candidate screen:

| Odds source | Best screened family | Bets | Profit | ROI | Active passed windows | Decision |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| AVG open | Portugal `P1` strong favorite probability bucket `[0.55,1.00]` | 208 | +133.40 | 6.41% | 2 / 6 | `REJECT_RESEARCH_GATES` |
| AVG close | Portugal `P1` strong favorite probability bucket `[0.55,1.00]` | 221 | -21.50 | -0.97% | 2 / 6 | `REJECT_RESEARCH_GATES` |

Interpretation:

- The apparent P1 favorite edge is not stable enough: the best open-price version only passes `33.33%` of active rolling windows.
- The same family turns negative on average closing prices, which is a warning that the signal is not a robust market-anchored edge.
- This is useful negative evidence: do not expand the allocation algorithm by adding P1 favorite slices just because aggregate open-price ROI is positive.
- The search should continue toward candidates that survive both monthly stability and cross-price sanity checks, or toward broader international historical odds that increase official-pool relevance.

Rolling low-correlation combo stress test:

- Code: `scripts/rolling_low_correlation_rule_selector.py`.
- Input market candidates:
  - `reports/market_bias_diagnostics_worldwide_avg_close/market_candidates.csv`.
  - `reports/market_bias_diagnostics_worldwide_ps_close/market_candidates.csv`.
- Reports:
  - `reports/rolling_low_correlation_rule_selector_trainstable_pair_relaxed_v2/summary.json`.
  - `reports/rolling_low_correlation_rule_selector_trainstable_pair_v2/summary.json`.
  - `reports/rolling_low_correlation_rule_selector_trainstable_pair_strict_v2/summary.json`.
- Purpose:
  - Re-check the attractive low-correlation combo idea with a prospective rolling protocol.
  - Select rules only from the prior 48 months.
  - Require each selected pair to pass training-window stability before testing the next 12-month validation window.

Result:

| Train pass-rate gate | Validation windows | Active passed windows | Bets | Profit | ROI | Decision |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 0.4 | 13 | 4 | 1125 | -48.48 | -4.31% | `REJECT_ROLLING_OOS` |
| 0.6 | 13 | 4 | 1125 | -48.48 | -4.31% | `REJECT_ROLLING_OOS` |
| 0.8 | 13 | 4 | 1125 | -48.48 | -4.31% | `REJECT_ROLLING_OOS` |

Interpretation:

- Static low-correlation combos can look attractive when the rule universe is chosen over the full sample, but prospective rolling selection does not preserve the edge.
- Raising the training stability gate from `0.4` to `0.8` did not improve sample-outcome quality for this compact pair-selection setup.
- The selected pairs still lose money over 2019-2026 validation windows and pass only `30.77%` of active windows.
- This rejects the current low-correlation-combo expansion as a deployable allocation algorithm.
- Future combo work must add a stronger non-price feature model or a stricter cross-provider/CLV confirmation layer, not merely combine more profitable historical buckets.

I2 final-bets CLV audit:

- Code: `scripts/i2_clv_audit.py`.
- Tests: `tests/test_i2_clv_audit.py`.
- Report: `reports/i2_final_bets_clv_audit/summary.json`.
- Input bets: `reports/feature_enriched_market_anchored_i2_stop3_cool3_v1/bets.csv`.
- Purpose:
  - Audit the actual final selected I2 draw bets, after the market-anchored filter and stop/cooldown risk control.
  - Join each selected bet back to football-data opening and closing 1X2 prices.
  - Separate raw CLV from no-vig closing fair edge.

Result:

| Metric | Value |
| --- | ---: |
| Input bets | 303 |
| Matched bets | 303 |
| Unmatched bets | 0 |
| Profit | +644.10 |
| ROI | 21.26% |
| Average bet odds | 3.2131 |
| Average closing draw odds | 3.1577 |
| Average raw CLV | +1.878% |
| Median raw CLV | +1.672% |
| Positive CLV rate | 73.60% |
| Positive / negative CLV months | 33 / 7 |
| Average no-vig closing edge | -4.843% |
| Decision | `RAW_CLV_CONFIRMED_RESEARCH_ONLY` |
| Warning | `avg_no_vig_closing_edge<=0` |

By season:

| Season | Bets | ROI | Avg raw CLV | Positive CLV rate | Avg no-vig closing edge |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2022-23 | 64 | 4.36% | +1.879% | 79.69% | -4.277% |
| 2023-24 | 74 | 11.80% | +2.203% | 75.68% | -4.001% |
| 2024-25 | 84 | 37.56% | +2.766% | 76.19% | -3.590% |
| 2025-26 | 81 | 26.35% | +0.657% | 64.20% | -7.360% |

Interpretation:

- This is the strongest supporting evidence for the current I2 direction so far: final selected bets consistently beat the raw closing draw price.
- However, the no-vig closing fair edge is still negative on average, so the result is not enough to claim a production-grade edge.
- The correct status is research-positive but not production-ready.
- Next validation should focus on whether official Sporttery SP offers similar positive raw CLV and whether a future prospective shadow sample reaches at least 200 settled selected bets across 6+ months.

I2 formal open-vs-close stress test:

- Code change: `scripts/feature_enriched_candidate_filter.py` now supports `--formal-i2-only`.
- Tests: `tests/test_feature_enriched_candidate_filter.py`.
- Reports:
  - `reports/feature_enriched_market_anchored_i2_formal_open_close_compare_v1/summary.json`.
  - `reports/feature_enriched_market_anchored_i2_formal_avg_close_v1/summary.json`.
  - `reports/feature_enriched_market_anchored_i2_formal_avg_close_cooldown_v1/summary.json`.
- Purpose:
  - Run the same formal market-anchored I2 draw configuration on opening average odds and closing average odds.
  - Check whether the signal disappears at close.
  - Apply the same settled-loss cooldown grid to the closing-odds selected bets as a research-only stress test.

Formal no-cooldown comparison:

| Odds source | Bets | Profit | ROI | Positive / Negative Months | Active passed windows |
| --- | ---: | ---: | ---: | --- | ---: |
| AVG open | 334 | +625.70 | 18.73% | 25 / 15 | 4 / 6 |
| AVG close | 335 | +439.90 | 13.13% | 21 / 19 | 3 / 6 |

Closing-odds cooldown grid:

| Variant | Bets | Profit | ROI | Positive / Negative Months | Active passed windows |
| --- | ---: | ---: | ---: | --- | ---: |
| stop3/cool14 | 218 | +549.10 | 25.19% | 23 / 17 | 5 / 6 |
| stop2/cool3 | 284 | +480.20 | 16.91% | 25 / 15 | 5 / 6 |
| stop3/cool3 | 302 | +278.00 | 9.21% | 20 / 20 | 3 / 6 |

Interpretation:

- The I2 market-anchored draw signal does not vanish at closing odds. That is stronger than a pure early-price artifact.
- Stability is weaker at close without cooldown: positive months narrow from `25 / 15` to `21 / 19`, and active passed windows fall from `4 / 6` to `3 / 6`.
- A post-hoc cooldown grid can recover a strong-looking closing-odds profile, especially `stop3/cool14`, but that parameter is selected after seeing the same historical period.
- Therefore `AVG_CLOSE + stop3/cool14` is a research lead, not a production parameter. It needs the same prospective freeze-and-shadow treatment as the current `AVG_OPEN + stop3/cool3`.
- The current I2 direction is now supported by three facts: positive multi-window opening performance, positive raw CLV, and positive closing-odds formal performance. The remaining blocker is official-SP prospective validation.

Frozen AVG-close research candidate:

- Manifest: `reports/profit_strategy_research_candidates/i2_avg_close_stop3_cool14_v1/manifest.json`.
- Scorer artifact: `reports/feature_enriched_market_anchored_i2_avg_close_scorer_v1/scorer.json`.
- Statistical audit: `reports/strategy_statistical_audit_market_anchored_i2_avg_close_stop3_cool14_v1/summary.json`.
- Edge calibration: `reports/strategy_edge_calibration_market_anchored_i2_avg_close_stop3_cool14_v1/summary.json`.
- Tests: `tests/test_profit_research_candidate_manifest.py`, `tests/test_profit_strategy_registry.py`.
- Strategy id: `profit-i2-draw-market-anchored-avg-close-stop3-cool14-v1`.
- Status: `STATISTICALLY_CALIBRATED_RESEARCH_LEAD_WAITING_OFFICIAL_SP_SHADOW`.

Frozen parameters:

| Parameter | Value |
| --- | --- |
| League | `I2` |
| Outcome | Draw |
| Odds source | `AVG_CLOSE` |
| Odds band | `[2.8,3.5)` |
| Train months | 30 |
| Min prior candidates | 120 |
| Min predicted EV | 0.02 |
| Ridge | 10 |
| Residual cap | 0.08 |
| Max bets per day | 1 |
| Settled-loss stop | 3 losing settlement days |
| Cooldown | 14 days |

Audit and calibration result:

| Check | Value |
| --- | ---: |
| Bets | 218 |
| Active months | 40 |
| Profit | +549.10 |
| ROI | 25.19% |
| Positive / negative months | 23 / 17 |
| Bootstrap ROI p05 | +8.79% |
| Probability ROI positive | 99.34% |
| Sign-flip p-value | 0.0128 |
| Drawdown / profit | 0.185 |
| Overall hit rate | 39.91% |
| Avg implied probability | 31.61% |
| Wilson lower hit rate | 33.64% |
| Conservative edge vs implied | +2.02 pp |

Freeze interpretation:

- The `AVG_CLOSE + stop3/cool14` variant is now frozen for prospective shadow validation.
- It now passes the formal monthly bootstrap/sign-flip audit and the overall selected-odds calibration audit.
- It is still explicitly blocked from production because the historical evidence uses football-data AVG_CLOSE rather than Chinese official SP, and because `cool14` was chosen after inspecting the historical cooldown grid.
- Season-level calibration is not uniformly conservative: `2022-23` is effectively flat/slightly negative, while later seasons carry most of the edge. This reinforces the need for prospective official-SP validation.
- The scorer can now be used in a future official-SP shadow workflow without changing the model coefficients or selection parameters.
- Promotion requires at least 200 settled selected official-SP shadow samples across at least 6 active months, positive ROI, positive month balance, and positive raw official-SP CLV.

Current official-SP validation status:

- Official pool diagnosis: `reports/profit_scorer_official_pool_avg_close_stop3_cool14/summary.json`.
- Official opening-snapshot validation: `reports/profit_scorer_official_sp_validation_avg_close_stop3_cool14/summary.json`.
- Strategy registry output: `reports/profit_strategies/summary.json`.

| Check | Value |
| --- | ---: |
| Current official pool scanned matches | 100 |
| Pool matches scored by AVG_CLOSE scorer | 0 |
| Pool matches passing scorer | 0 |
| Opening pre-match official snapshots | 28 |
| Opening snapshots scored | 0 |
| Selected official-SP snapshots | 0 |
| Settled selected official-SP snapshots | 0 |

Official-SP blocker interpretation:

- The current official pool blocker is coverage, not model arithmetic: `league_not_i2` blocks all `100` current official-pool matches.
- In the historical opening-snapshot validation set, `28 / 28` snapshots are also blocked by `league_not_i2`, and `19 / 28` are outside the draw SP band `[2.8,3.5)`.
- This means the algorithm is ready for I2 official-SP shadow validation, but the current Chinese official pool does not contain eligible I2 fixtures.
- Do not widen the strategy to World Cup or FIN to force daily bets; those domains already failed their own stability checks.

Broad International Odds Data Status:

- Code: `football_agents/international_odds_agent.py` now supports football-data.co.uk World Cup workbook odds, Footiqo World Cup fallback odds, and The Odds API historical h2h snapshots.
- CLI:
  - Default free World Cup / World Cup qualifiers source: `python -m football_agents.cli sync-international-odds-history --provider football-data-world-cup`.
  - Footiqo fallback source: `python -m football_agents.cli sync-international-odds-history --provider footiqo`.
  - Paid/broader provider: `python -m football_agents.cli sync-international-odds-history --provider odds-api --sport-keys soccer_uefa_nations_league --from-date 2024-09-06 --to-date 2024-09-06 --max-snapshots 1`.
- Output:
  - Default World Cup CSV: `data/historical_csv/football-data/new/WORLD_CUP.csv`.
  - football-data workbook archive: `data/historical_csv/footiqo/world_cup_football_data.xlsx`.
  - Raw archive root: `data/historical_csv/the_odds_api/international`.
  - Converted CSV: `data/historical_csv/football-data/new/INTERNATIONAL_ODDS_API.csv`.
- Current football-data workbook sync:
  - Source: `https://www.football-data.co.uk/WorldCup2026.xlsx`.
  - Matched rows: `1146`.
  - Dropped rows: `7`.
  - Coverage: World Cup 2014, 2018, 2022, 2026 plus World Cup 2026 qualifiers.
  - Date range: `12/06/2014` through `28/06/2026`.
- Conversion guardrail:
  - The adapter writes only events that have h2h home/draw/away prices and can be matched to already-settled national-team results by date/home/away.
  - Unmatched events are dropped, so the dataset does not leak future results into strategy research.
- Current real-environment probe:
  - `/sports` verification works with the configured key and returns usable international keys for World Cup, UEFA Euro, Copa America, and UEFA Nations League.
  - Historical odds fetch for `soccer_uefa_nations_league` on `2024-09-06` returned `HTTP Error 401: Unauthorized`.
  - Interpretation: the current The Odds API key is valid for sport discovery/live usage but does not currently have historical odds access.
- Algorithm implication:
  - Free public data can fill national-team features, but broad international betting-edge validation still requires paid historical 1X2 odds access or another equivalent odds archive.
  - Until that access is available and archived, do not promote World Cup/Euro/Copa/Nations League allocation rules from result-only data.
- Source discovery update:
  - `python -m football_agents.cli research-international-odds-sources` now reports a structured `source_decision`.
  - Best feature source: `martj42 international_results`, already archived at `data/historical_csv/international/results.csv`.
  - Best free odds source: football-data.co.uk World Cup workbook, converted to `data/historical_csv/football-data/new/WORLD_CUP.csv`.
  - Best broad international odds source: The Odds API historical h2h snapshots.
  - Fallback commercial candidates: SportsGameOdds historical odds, API-Football/API-Sports odds, and Sportmonks Premium Odds Feed. These require coverage probing and new adapters before they can be used for no-leakage edge validation.

Daily Allocation Readiness:

- Code: `football_agents/profit_allocation_readiness.py`.
- CLI: `python -m football_agents.cli profit-allocation-readiness --daily-budget 100 --output reports/profit_allocation_readiness/summary.json`.
- Config: `PROFIT_DAILY_BUDGET`, default `100`.
- Report: `reports/profit_allocation_readiness/summary.json`.

Current result:

| Check | Value |
| --- | ---: |
| Daily budget | 100 |
| Allocated budget | 0 |
| Cash reserved | 100 |
| Decision | `WAIT_FOR_VALIDATED_OFFICIAL_SP_COVERAGE` |

Interpretation:

- The system now treats "do not invest today" as a first-class allocation decision, not as an unexplained pile of `NO_BET` rows.
- Both registered I2 strategy packages are historically supported by statistical audit and edge calibration, but neither currently passes official-SP coverage/settlement gates.
- The AVG_CLOSE candidate's current top official-pool blocker remains `league_not_i2`, followed by draw-SP band and invalid official-SP issues.
- This is the correct behavior for the project objective: do not force the daily 100 into World Cup/FIN/international matches that failed or lack validated odds-edge history.
- Future daily allocation becomes available only after a strategy has:
  - `STATISTICALLY_SUPPORTED_RESEARCH_CANDIDATE`.
  - `CALIBRATED_EDGE_CONFIRMED`.
  - `OFFICIAL_SP_PROSPECTIVE_PASS`.
  - At least `200` settled selected official-SP shadow samples across the required active-month window.

Historical Data Domain Readiness:

- Code: `football_agents/profit_data_domain_readiness.py`.
- CLI: `python -m football_agents.cli profit-data-domain-readiness --output reports/profit_data_domain_readiness/summary.json`.
- API: `GET /api/profit/data-domain-readiness`.
- Report: `reports/profit_data_domain_readiness/summary.json`.

Current scan:

| Check | Value |
| --- | ---: |
| Historical domains scanned | 36 |
| Search-ready domains not already rejected | 31 |
| Existing watch-only domains | 2 |
| Existing rejected domains | 2 |
| Result-only/no-odds domains | 1 |

Top interpretation:

- `I2` remains the highest-priority profit domain because it already has a statistically supported/calibrated strategy; the blocker is official-pool coverage, not lack of historical evidence.
- `FIN` has enough historical odds and is present in the current official pool, but it is now explicitly marked `REJECTED_BY_EXISTING_STABILITY_GATES` / `LOW_DO_NOT_LOOSEN`, so the system will not recommend loosening FIN thresholds simply to force daily bets.
- `WORLD_CUP` is also marked `REJECTED_BY_EXISTING_STABILITY_GATES` because the tournament holdout rejected reusable rules and the sample is too small.
- `SP1` and `JPN` are watch-only: both have signals worth tracking, but each has already failed at least one promotion/stability gate.
- Large untested search-ready domains include `ARG`, `USA`, `BRA`, `MEX`, `ROU`, `POL`, `NOR`, `SWE`, `RUS`, `DNK`, and `CHN`. These are candidates for future no-lookahead searches, but they are not current official-pool allocation domains.

Next algorithmic action:

- Do not spend effort loosening FIN or World Cup.
- Keep I2 frozen for official-SP coverage.
- For finding a new reusable algorithm, run no-lookahead diagnostics on the highest-ranked untested odds-backed domains, then require the same walk-forward, statistical audit, calibration, and official-SP validation gates before any daily allocation.

Batch Domain Discovery Round 1:

- Code: `scripts/batch_profit_domain_discovery.py`.
- Input: `reports/profit_data_domain_readiness/summary.json`.
- Batch report: `reports/batch_profit_domain_discovery_top3_v1/summary.json`.
- Candidate screens:
  - `reports/market_bias_candidate_screen_usa_max_close_top8_v1/summary.json`.
  - `reports/market_bias_candidate_screen_arg_avg_close_top8_v1/summary.json`.
  - `reports/market_bias_candidate_screen_bra_avg_close_top8_v1/summary.json`.

First-pass domains:

| Domain | Odds source | Diagnostic rows | First-pass signal | Candidate-screen result |
| --- | --- | ---: | --- | --- |
| `USA` | `MAX_CLOSE` | 74 | Low-price home favorite buckets, about `1.8%` to `2.0%` raw ROI | Rejected: 56 bets, month balance `4 / 4`, drawdown `62.9` > profit `23.7` |
| `BRA` | `AVG_CLOSE` | 12 | Home `[1.8,2.2)` buckets, below `1%` raw ROI | Rejected: no candidate survived rolling selection |
| `ARG` | `AVG_CLOSE` | 3 | Home non-favorite / low market-probability bucket | Rejected: only 4 walk-forward bets |

Interpretation:

- The first untested high-sample domains did not produce a reusable allocation algorithm.
- This is negative progress, but it is the right kind: it rejects weak broad-domain market-bias patterns before they reach shadow allocation.
- The USA result is especially instructive: a broad raw diagnostic can show many positive months, but the no-lookahead portfolio gate still rejects it when the selected walk-forward sample is too small and drawdown dominates profit.
- Continue the search on additional untested domains, but keep the same rejection standard. Do not promote any domain on first-pass raw diagnostic ROI alone.

Batch Domain Discovery Round 2:

- Batch report: `reports/batch_profit_domain_discovery_next5_v1/summary.json`.
- Candidate screens:
  - `reports/market_bias_candidate_screen_mex_avg_close_top8_v1/summary.json`.
  - `reports/market_bias_candidate_screen_nor_avg_close_top8_v1/summary.json`.
  - `reports/market_bias_candidate_screen_swe_avg_close_top8_v1/summary.json`.

Second-pass domains:

| Domain | Odds source | Diagnostic rows | First-pass signal | Candidate-screen result |
| --- | --- | ---: | --- | --- |
| `MEX` | `AVG_CLOSE` | 7 | Low-price favorite bucket, raw ROI up to `4.03%` | Rejected: no candidate survived rolling selection |
| `NOR` | `AVG_CLOSE` | 20 | Away low-price and favorite buckets | Rejected: 49 bets, `-16.61%` ROI, negative month/season balance |
| `SWE` | `AVG_CLOSE` | 26 | Away `[2.2,2.8)` showed high sample-out ROI | Rejected: only 23 bets, season balance `1 / 1`, below sample gate |
| `ROU` | `AVG_CLOSE` | 4 | Weak away favorite bucket, below `1%` raw ROI | Not advanced beyond first-pass diagnostics |
| `POL` | `AVG_CLOSE` | 0 | No qualifying diagnostic rows | Not advanced |

Interpretation:

- The second batch also failed to produce a reusable allocation candidate.
- `SWE away [2.2,2.8)` is the tempting result, but it is exactly the kind of sparse rule the process is designed to reject: high ROI, only 23 walk-forward bets, and no season-level dominance.
- `NOR` shows why raw diagnostics are not enough: the sample-out portfolio flips strongly negative.
- The current evidence still supports keeping I2 as the only statistically calibrated lead, while expanding search rather than lowering gates.

Batch Domain Discovery Round 3:

- Batch report: `reports/batch_profit_domain_discovery_next5_v2/summary.json`.
- Candidate screens:
  - `reports/market_bias_candidate_screen_rus_avg_close_top8_v1/summary.json`.
  - `reports/market_bias_candidate_screen_dnk_avg_close_top8_v1/summary.json`.
  - `reports/market_bias_candidate_screen_chn_avg_close_top8_v1/summary.json`.
  - `reports/market_bias_candidate_screen_e1_b365_open_top8_v1/summary.json`.
  - `reports/market_bias_candidate_screen_e3_b365_close_top8_v1/summary.json`.
- Code fix: `scripts/batch_profit_domain_discovery.py` now supports classic football-data league codes such as `E1` and `E3` by loading their season files and filtering the target league, instead of assuming every code exists under `football-data/new`.

Third-pass domains:

| Domain | Odds source | Diagnostic rows | First-pass signal | Candidate-screen result |
| --- | --- | ---: | --- | --- |
| `RUS` | `AVG_CLOSE` | 14 | Home `[2.2,2.8)` raw ROI `7.73%` | Rejected: 27 bets, `-16.48%` ROI, drawdown `70.4` |
| `DNK` | `AVG_CLOSE` | 8 | Draw/favorite buckets, raw ROI up to `5.55%` | Rejected: 17 bets, `-20.29%` ROI for the best advancing rule |
| `CHN` | `AVG_CLOSE` | 7 | Draw market-probability bucket raw ROI `13.5%` | Rejected: 50 bets, `-22.28%` ROI, drawdown `192.4` |
| `E1` | `B365_OPEN` | 3 | Mid-price favorite bucket raw ROI `10.93%` | Rejected: no candidate survived rolling selection |
| `E3` | `B365_CLOSE` | 3 | Mid-price favorite bucket raw ROI `1.39%` | Rejected: no walk-forward bets |

Interpretation:

- This is the strongest negative evidence so far against a simple market-bucket algorithm outside I2.
- `CHN` is particularly important: the raw diagnostic looked excellent, but the rolling no-lookahead portfolio turned sharply negative. That is exactly the failure mode the monthly walk-forward gate is meant to catch.
- After 13 newly scanned/search-screened domains, no simple market-bias bucket has passed the current stability and portfolio gates.
- The next productive step is to move beyond raw market-bias buckets into feature-enriched residual models or multi-domain models with strict out-of-sample gates, while keeping I2 as the only calibrated lead.

Residual Model Walk-Forward Round 1:

- Code: `scripts/walk_forward_residual_strategy.py`.
- Code update:
  - The CLI now supports `--seasons`, instead of hard-coding only `2324` and `2425`.
  - Added `stability` profile with larger validation sample and validation drawdown/profit constraints.
  - Tightened promotion gate: positive ROI is not enough; total profit must exceed max drawdown and profitable invested months must exceed losing invested months.
- Test command: `pytest tests/test_walk_forward_residual_strategy.py -q`.
- Test result: `7 passed`.

Experiments:

| Report | Window | Profile | Bets | Profit | ROI | Max drawdown | Month balance | Decision |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `reports/residual_walk_forward_5season_relaxed_2025_06_v1` | 2025-06 through 2026-05 | relaxed | 35 | 9.62 | 19.38% | 8.54 | mixed, small sample | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_stability_2025_06_v1` | 2025-06 through 2026-05 | stability | 10 | -0.46 | -4.14% | 5.32 | too few bets | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_bucketed_2025_06_v1` | 2025-06 through 2026-05 | bucketed | 6 | -6.00 | -100.00% | 6.00 | overfit buckets | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_relaxed_2024_06_v1` | 2024-06 through 2026-05 | relaxed | 135 | 11.12 | 7.01% | 15.13 | 6 profitable / 5 losing invested months | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_strict_2024_06_v1` | 2024-06 through 2026-05 | strict | 88 | 1.58 | 1.52% | 15.43 | 5 profitable / 6 losing invested months | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_guarded_2024_06_v1` | 2024-06 through 2026-05 | guarded | 27 | -7.81 | -28.37% | 9.81 | 0 profitable / 3 losing invested months | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_draw_value_2024_06_v1` | 2024-06 through 2026-05 | draw_value | 51 | 4.69 | 9.18% | 6.10 | 3 profitable / 3 losing invested months | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_draw_value_stop_2024_06_v1` | 2024-06 through 2026-05 | draw_value_stop | 27 | -2.22 | -8.19% | 4.70 | 2 profitable / 3 losing invested months | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_draw_regime_2024_06_v1` | 2024-06 through 2026-05 | draw_regime | 38 | 5.84 | 15.33% | 7.32 | 4 profitable / 2 losing invested months | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_draw_regime_strict_2024_06_v1` | 2024-06 through 2026-05 | draw_regime_strict | 33 | 2.24 | 6.79% | 8.22 | 3 profitable / 2 losing invested months | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_draw_quality_2024_06_v1` | 2024-06 through 2026-05 | draw_quality | 15 | -0.54 | -3.60% | 5.00 | 1 profitable / 2 losing invested months | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_draw_quality_pooled_2024_06_v1` | 2024-06 through 2026-05 | draw_quality_pooled | 0 | 0.00 | 0.00% | 0.00 | 0 profitable / 0 losing invested months | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_5season_draw_quality_pooled_lite_2024_06_v1` | 2024-06 through 2026-05 | draw_quality_pooled_lite | 25 | -3.22 | -12.88% | 9.80 | 4 profitable / 6 losing invested months | `NEED_MORE_DATA` |

Interpretation:

- The residual model is more promising than simple market-bucket rules because it produced 135 no-lookahead bets over 24 months with positive ROI and good aggregate calibration (`ECE 0.003117`).
- It is not yet a production money-making algorithm: max drawdown (`15.13`) exceeds total profit (`11.12`), so the profit is too fragile to promote.
- The `bucketed` experiment is a clear warning against tiny validation buckets: validation ROI looked extreme, but the next-month sample lost every bet.
- The `strict` and `guarded` experiments show that simply tightening EV thresholds, reducing Kelly, and requiring stronger validation drawdown/profit ratios does not solve the problem; it mostly removes upside or leaves the same bad months.
- The `draw_value` experiment is the cleanest structural lead so far: forcing residual candidates into draw value ranges improves ROI versus strict/guarded and removes most home/away drag, but drawdown still exceeds profit.
- The `draw_value_stop` experiment shows that a simple monthly stop loss is not enough. It reduces max drawdown from `6.10` to `4.70`, but flips profit negative, so the issue is candidate quality/regime detection rather than only staking cadence.
- The `draw_regime` experiment adds a no-lookahead second-stage gate: each month it selects draw-value candidates only from validation-positive regime buckets such as market draw probability, prior league draw rate, strength gap, and goal environment. This improves ROI to `15.33%` and month balance to `4 / 2`, but still fails the profit-over-drawdown gate (`5.84` profit versus `7.32` max drawdown).
- The stricter regime version reduces sample and upside without improving drawdown, so simply tightening bucket sample/ROI thresholds is not enough.
- The first candidate-quality model (`draw_quality`) used a no-lookahead validation split: the earlier validation months trained a linear unit-profit score, the final validation month selected the configuration, and the full validation window retrained the gate for the test month. It failed out-of-sample (`-3.60%` ROI), mainly because the 3-month validation window leaves too few quality-model samples.
- The pooled quality holdout model used a 12-month validation window but still abstained in all test months because the final validation-month gate was too selective after quality filtering.
- The pooled quality lite model used the full 12-month validation window for quality training/selection and a small fixed grid. It produced many strong validation summaries but still lost out-of-sample (`-12.88%` ROI), which is evidence that the linear quality score is chasing historical noise rather than learning a stable candidate-quality edge.
- Current best route: keep residual probability modeling and draw-regime constraints, but do not use the current linear quality gates for allocation. The most promising surviving research candidate remains `draw_regime`, while the next quality-model attempt needs either richer features, stronger regularization/monotonic constraints, or a different validation design. Do not promote small bucket filters, relaxed residual output, stop-loss-only variants, current draw-regime variants, or first-pass quality gates until the drawdown/profit gate is passed over a longer sample.

World Cup / International Odds Expansion Validation:

- Data update:
  - `sync-international-odds-history --provider football-data-world-cup` archived `1146` football-data World Cup / World Cup qualifiers matches with complete `AvgCH/AvgCD/AvgCA`.
  - Date range: `2014-06-12` through `2026-06-28`.
  - Competitions in the converted file: World Cup 2014, 2018, 2022, 2026, and World Cup Qualifiers.
- Code:
  - `scripts/world_cup_tournament_validation.py` now supports `--mode rolling`.
  - Rolling mode discovers rules only from years earlier than the test year, which fits sparse tournament/qualifier data better than monthly league windows.
- Tests:
  - `pytest tests/test_world_cup_tournament_validation.py -q`
  - Result: `3 passed`.
- Reports:
  - `reports/world_cup_tournament_validation_2018_2022_newdata_v1/summary.json`.
  - `reports/market_bias_diagnostics_world_cup_avg_close_newdata_v1/summary.json`.
  - `reports/market_bias_diagnostics_world_cup_max_close_newdata_v1/summary.json`.
  - `reports/market_bias_candidate_screen_world_cup_newdata_v1/summary.json`.
  - `reports/world_cup_rolling_validation_avg_close_newdata_v1/summary.json`.
  - `reports/world_cup_rolling_validation_max_close_newdata_v1/summary.json`.
  - `reports/world_cup_rolling_validation_avg_close_current_research/summary.json`.
  - `reports/world_cup_rolling_validation_max_close_current_research/summary.json`.

Results:

| Validation | Odds source | Candidates / rules | Best apparent result | Decision |
| --- | --- | ---: | --- | --- |
| Tournament holdout 2018 -> 2022 | `AVG_CLOSE` | 20 | No rule passed; several 2018 winners failed in 2022 | `REJECT_NO_REUSABLE_WORLD_CUP_RULE` |
| Full-sample diagnostics | `AVG_CLOSE` | 26 diagnostic rows | `[2.8,3.5)` odds bucket: 543 bets, +11.83 units, 2.18% ROI | Diagnostics only |
| Full-sample diagnostics | `MAX_CLOSE` | 81 diagnostic rows | `[3.5,4.0)` / draw-like buckets show high raw ROI | Diagnostics only |
| Monthly league-style candidate screen | `AVG_CLOSE,MAX_CLOSE` | 24 checked rows | 0 walk-forward bets because sparse tournament data breaks 12-month league windows | 0 passed |
| Rolling yearly holdout | `AVG_CLOSE` | 88 combined rules | `[2.8,3.5)` had 255 out-of-sample bets, +10.71 units, 4.20% ROI, but max drawdown 13.22 > profit 10.71 | `REJECT_NO_REUSABLE_WORLD_CUP_ROLLING_RULE` |
| Rolling yearly holdout | `MAX_CLOSE` | 111 combined rules | Best combined rules had strong ROI but only 15-64 out-of-sample bets or failed month/drawdown gates | `REJECT_NO_REUSABLE_WORLD_CUP_ROLLING_RULE` |

Daily portfolio validation:

- Code: `scripts/world_cup_tournament_validation.py --mode portfolio`.
- Selection rule:
  - Each test year uses only earlier years to discover rules.
  - Training rule edge is shrunk by sample size and penalized by drawdown.
  - Test-year bets are deduplicated by match/outcome before staking.
  - Daily bankroll policy is `daily_limit=100`, `max_single_stake=10`, settlement delay `1` day.
- Reports:
  - `reports/world_cup_portfolio_validation_avg_close_current_research/summary.json`.
  - `reports/world_cup_portfolio_validation_max_close_current_research/summary.json`.
  - `reports/world_cup_portfolio_validation_avg_close_nonlongshot_current_research/summary.json`.
  - `reports/world_cup_portfolio_validation_max_close_draw_filtered_current_research/summary.json`.
  - `reports/world_cup_portfolio_grid_current_research/summary.json`.

| Portfolio experiment | Bets | Staked | Profit | ROI | Max DD | Month balance | Year balance | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| `AVG_CLOSE`, top 3 rules | 233 | 2219.96 | -148.84 | -6.70% | 359.44 | 7 / 12 | 2 / 4 | `REJECT_WORLD_CUP_PORTFOLIO_WEAK` |
| `MAX_CLOSE`, top 3 rules | 329 | 3259.97 | -767.17 | -23.53% | 837.87 | 7 / 12 | 1 / 5 | `REJECT_WORLD_CUP_PORTFOLIO_WEAK` |
| `AVG_CLOSE`, odds <= 3.5, market probability >= 0.20 | 167 | 1670.00 | +4.20 | 0.25% | 177.70 | 7 / 12 | 3 / 3 | `REJECT_WORLD_CUP_PORTFOLIO_WEAK` |
| `MAX_CLOSE`, draw only, odds <= 5.0, market probability >= 0.20 | 126 | 1260.00 | +67.70 | 5.37% | 240.50 | 7 / 5 | 2 / 1 | `REJECT_WORLD_CUP_PORTFOLIO_WEAK` |

Portfolio grid search:

- Command:
  - `python scripts/world_cup_tournament_validation.py --mode portfolio-grid --odds-sources AVG_CLOSE,MAX_CLOSE --first-test-year 2018 --top-n 20 --grid-max-rules 1,2 --min-train-samples 20 --min-train-active-months 1 --min-test-bets 40 --min-roi-pct 1 --daily-limit 100 --max-single-stake 10 --grid-allowed-outcomes "all;draw" --grid-max-odds "3.5,5.0,none" --grid-min-market-probabilities "0.2,0.28" --output-dir reports/world_cup_portfolio_grid_current_research`
- Configs tested: `48`.
- Passed configs: `0`.
- Decision: `REJECT_GRID_BEST_POSITIVE_BUT_UNSTABLE`.
- Best row:
  - `MAX_CLOSE`, draw only, `max_rules=1`, odds `<=5.0`, market probability `>=0.20`.
  - 126 bets, staked 1260.00, profit +67.70, ROI 5.37%, max drawdown 240.50.
  - Rejection reason: `drawdown>profit`.

Interpretation:

- The expanded World Cup/qualifier source is useful data, but it still does not produce a production-grade money allocation algorithm.
- `AVG_CLOSE` has a broad weak signal around odds `[2.8,3.5)`, but profit does not cover drawdown.
- `MAX_CLOSE` creates attractive-looking 2026 fold winners, including draw odds `[3.5,4.0)`, but the combined no-lookahead sample fails the minimum-bet and stability gates. This is a classic “good year, not good algorithm” pattern.
- The daily portfolio experiment confirms the same diagnosis under money allocation: raw yearly rule selection loses money, while the best filtered draw-only configuration is positive but has drawdown `240.50` against only `67.70` profit and lost the full 2025 test year. That is not true EV.
- The formal 48-config grid confirms that the best World Cup configuration is a near-miss, not a valid allocation strategy. Tightening away from longshots either collapses sample size or turns profit negative.
- Do not promote World Cup / qualifier rules into daily allocation from this evidence. Keep the data for feature support and future model experiments, but the search for a reusable profitable algorithm should continue outside these rejected tournament-only market-bucket rules.

Low-Correlation Multi-Domain Rule Combination Audit:

- Code:
  - `scripts/low_correlation_rule_combo_search.py`.
  - `scripts/rolling_low_correlation_rule_selector.py`.
- Code update:
  - `rolling_low_correlation_rule_selector.py` now accepts either `unit_profit` or `profit` input columns, so direct rule pools can be re-used in rolling no-lookahead validation.
- Test:
  - `pytest tests/test_rolling_low_correlation_rule_selector.py -q`.
  - Result: `2 passed`.

Why this audit matters:

- Full-sample low-correlation combinations looked promising:
  - `reports/low_correlation_rule_combo_search_worldwide_top20_combo3_v1/summary.json` best combo: 1652 bets, +123.03 units, 7.45% ROI, active pass rate 0.68.
  - `reports/low_correlation_rule_combo_search_worldwide_cross_source_top12_combo3_v1/summary.json` best combo: 2158 bets, +151.35 units, 7.01% ROI, active pass rate 0.60.
- But those full-sample combinations are not sufficient because the rule set is selected with information from the full period. They must survive rolling no-lookahead selection.

New non-overlapping yearly rolling checks:

| Report | Candidate pool | Config | Bets | Profit | ROI | Active windows | Active pass rate | Decision |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `reports/rolling_low_correlation_rule_selector_cross_source_pair_nonoverlap_v1/summary.json` | Cross-source top12 direct rules | Pair combo, 48m train, 12m test, 12m step | 421 | -6.46 | -1.53% | 4 | 0.25 | Rejected |
| `reports/rolling_low_correlation_rule_selector_top20_combo3_nonoverlap_v1/summary.json` | Top20 direct rules | 3-rule combo, 48m train, 12m test, 12m step | 726 | -6.04 | -0.83% | 7 | 0.1429 | Rejected |
| `reports/rolling_low_correlation_rule_selector_cross_source_pair_stricter_nonoverlap_v1/summary.json` | Cross-source top12 direct rules | Stricter 60m train / 0.8 train pass / corr <= 0.25 | 0 | 0.00 | 0.00% | 0 | 0.00 | Abstains |
| `reports/rolling_low_correlation_rule_selector_top20_combo3_stricter_nonoverlap_v1/summary.json` | Top20 direct rules | Stricter 60m train / 0.8 train pass / corr <= 0.25 | 213 | -12.86 | -6.04% | 2 | 0.00 | Rejected |

Interpretation:

- Low-correlation portfolio construction improves the full-sample story, but it does not solve rule-selection instability.
- The same rule families that look profitable when chosen with hindsight fail once each yearly test window can only use earlier data.
- Tightening the train stability gate either abstains completely or still loses, so the issue is not simply that the earlier filter was too loose.
- Do not promote multi-domain low-correlation market-bucket combinations. The next algorithmic step should move away from hand-picked market buckets toward either:
  - a properly regularized feature model trained only on prior windows, or
  - a frozen I2-style candidate that passes official-SP prospective validation.

Real EV Recalibration Round:

- Problem diagnosed:
  - The prior EV path used model probability directly: `EV = model_probability * official_sp - 1`.
  - This created a structural bias where high-odds weak sides often appeared positive EV, even when the market-implied probability did not support that view.
  - A 2,500-match historical audit found `2060` positive-EV options with odds `>=3.0` under the old model-EV view, which is not a credible long-run betting edge.
- Code:
  - Added `football_agents/real_ev.py`.
  - `football_agents/true_odds_engine.py` now produces `real_ev` and `real_ev_calibration`.
  - `football_agents/agents/workflow.py` now selects candidates and stores signal EV from True Odds / real EV, while keeping `model_ev` only as diagnostics.
  - `football_agents/edge_quality_optimizer.py` now uses true probability for true-odds stake and EV reporting.
  - `scripts/walk_forward_residual_strategy.py` now applies the same real-EV market anchor in the monthly walk-forward residual strategy and writes `model_probability`, `model_lower_ev`, and `model_ev` diagnostics to `bets.csv`.
- Method:
  - Market no-vig probability is treated as the prior.
  - Model residuals are retained only according to data reliability.
  - Home/away longshot positive residuals receive tight caps and explicit penalties.
  - Normal draw prices around `2.4-4.0` are not treated as weak-team longshots, but still require enough residual edge to beat margin and uncertainty.
- Tests:
  - `pytest tests/test_real_ev.py tests/test_true_odds_engine.py tests/test_walk_forward_residual_strategy.py -q`
  - Result: `23 passed`.

Historical audit after recalibration:

| Audit | Old model EV positives | New real EV positives | Interpretation |
| --- | ---: | ---: | --- |
| Odds `>=3.0`, first 2,500 scanned 2526 historical rows | 2060 | sharply reduced after real-EV anchor | Old longshot/weak-side EV was mostly model overconfidence |
| 2025-01 residual prediction distribution | home real EV > 0: 0; away real EV > 0: 0; draw real EV > 0: 3 | draw lower-bound EV > 0: 2 | New signal is sparse and mostly draw-specific |

New walk-forward reports:

| Report | Profile | Window | Bets | Profit | ROI | Max drawdown | Month balance | Decision |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `reports/residual_walk_forward_real_ev_guarded_2024_06_v1` | guarded | 2024-06 through 2026-05 | 0 | 0.00 | 0.00% | 0.00 | 0 / 0 | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_real_ev_draw_quality_pooled_lite_2024_06_v2` | draw_quality_pooled_lite | 2024-06 through 2026-05 | 0 | 0.00 | 0.00% | 0.00 | 0 / 0 | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_real_ev_probe_draw_2024_06_v1` | real_ev_probe_draw | 2024-06 through 2026-05 | 5 | 1.40 | 28.00% | 2.00 | 1 profitable / 3 losing active months | `NEED_MORE_DATA` |

Statistical audit for `real_ev_probe_draw`:

- Report: `reports/residual_walk_forward_real_ev_probe_draw_2024_06_v1/statistical_audit.json`.
- Decision: `REJECT_STATISTICALLY_WEAK`.
- Reasons:
  - `bets<minimum`.
  - `active_months<minimum`.
  - `bootstrap_roi_p05<=0`.
  - `bootstrap_positive_probability<0.95`.
  - `sign_flip_p_value>0.05`.
  - `drawdown_to_profit>0.5`.
  - `positive_months<=negative_months`.

Interpretation:

- The real-EV change fixed the weak-team longshot EV pathology, but it also shows that most previous apparent edges were not robust enough to survive market anchoring and uncertainty.
- The remaining signal is sparse and draw-heavy, especially around Spanish leagues in this 24-month window, but the sample is far too small to allocate real daily capital.
- This is useful progress because it separates two things:
  - old false edge: model residuals too large versus the betting market;
  - surviving research lead: a small draw-value residual signal that needs broader data, richer draw-specific features, and more samples.
- Do not promote `real_ev_probe_draw`.
- Next algorithmic step:
  - keep the real-EV anchor as the production EV definition;
  - expand draw-specific features and validation samples;
  - search for enough repeated draw-value signals that pass profit-over-drawdown and statistical audit gates before any daily 100 allocation is considered live.

Draw-Specific Feature Expansion Round:

- Motivation:
  - The first real-EV probe produced only `5` bets. It was positive on paper, but statistically weak.
  - The surviving signal was draw-heavy, so the next step was to add draw-specific pre-match features instead of loosening weak-side EV.
- Code:
  - `scripts/walk_forward_residual_strategy.py` now adds:
    - `home_recent_draw_rate`, `away_recent_draw_rate`, `combined_recent_draw_rate`.
    - `home_recent_low_score_rate`, `away_recent_low_score_rate`, `combined_recent_low_score_rate`.
    - `draw_market_vs_league`, comparing no-vig market draw probability with prior league draw rate.
    - Buckets: `recent_draw_bucket`, `recent_low_score_bucket`, `draw_market_gap_bucket`.
  - These features are built only from matches before the current match date.
  - The residual model design matrix now includes these draw-specific features.
  - Added research-only profiles:
    - `real_ev_draw_regime_features`.
    - `real_ev_draw_regime_features_fast`.
- Tests:
  - `pytest tests/test_walk_forward_residual_strategy.py -q`
  - Result: `21 passed`.

Experiments:

| Report | Profile | Window | Bets | Profit | ROI | Max drawdown | Month balance | Decision |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- | --- |
| `reports/residual_walk_forward_real_ev_draw_regime_features_fast_2024_06_v1` | real_ev_draw_regime_features_fast | 2024-06 through 2026-05 | 0 | 0.00 | 0.00% | 0.00 | 0 / 0 | `NEED_MORE_DATA` |
| `reports/residual_walk_forward_real_ev_probe_draw_features_2024_06_v1` | real_ev_probe_draw with draw features | 2024-06 through 2026-05 | 15 | 2.80 | 18.67% | 4.00 | 4 profitable / 1 losing active months | `NEED_MORE_DATA` |

Statistical audit for `real_ev_probe_draw_features`:

- Report: `reports/residual_walk_forward_real_ev_probe_draw_features_2024_06_v1/statistical_audit.json`.
- Decision: `POSITIVE_BUT_NOT_STATISTICALLY_CONFIRMED`.
- Key values:
  - Bets: `15`.
  - Active months: `5`.
  - ROI: `18.67%`.
  - Bootstrap ROI 5th percentile: `-6.25%`.
  - Bootstrap positive ROI probability: `0.876`.
  - Sign-flip p-value: `0.223`.
- Rejection reasons:
  - `bets<minimum`.
  - `active_months<minimum`.
  - `bootstrap_roi_p05<=0`.
  - `bootstrap_positive_probability<0.95`.
  - `sign_flip_p_value>0.05`.

Interpretation:

- The new draw features improved the sparse probe from `5` bets to `15` bets and improved active-month balance from `1 / 3` to `4 / 1`.
- The bucketed feature regime failed because validation-selected buckets did not recur in the test months; this is still a small-sample instability problem.
- The unbucketed draw-feature probe is the best current real-EV research lead, but it remains far below the minimum evidence required for a daily 100 yuan allocation strategy.
- Do not promote this profile. Treat it as a research lead:
  - broaden the data sample;
  - add more recurring draw-value markets;
  - require at least `50` out-of-sample bets and `6` active months before considering it more than exploratory.

Draw Candidate Ranking Round:

- Motivation:
  - `real_ev_probe_draw_features` improved sample and month balance, but max drawdown still exceeded observed profit.
  - The next hypothesis was that selecting only the strongest daily draw candidate could reduce drawdown without reintroducing bucket instability.
- Code:
  - `PortfolioConfig` now supports:
    - `candidate_limit_per_day`.
    - `ranking_key`.
  - `simulate()` sorts daily candidates by the configured ranking key and limits the number of candidates before staking.
  - Added research-only profiles:
    - `real_ev_draw_ranked`.
    - `real_ev_draw_ranked_fast`.
- Test:
  - `pytest tests/test_walk_forward_residual_strategy.py -q`
  - Result: `24 passed`.
- Main experiment:
  - Report: `reports/residual_walk_forward_real_ev_draw_ranked_fast_2024_06_v1`.
  - Profile: one ranked draw candidate per day, ranked by `lower_ev`.
  - Window: 2024-06 through 2026-05.
  - Bets: `9`.
  - Profit: `2.80`.
  - ROI: `31.11%`.
  - Max drawdown: `2.00` in daily equity summary; active-month audit has no negative month.
  - Active betting months: `2`.
  - Profitable months: `2`.
  - Losing months: `0`.
  - Promotion: `NEED_MORE_DATA`.
- Statistical audit:
  - Report: `reports/residual_walk_forward_real_ev_draw_ranked_fast_2024_06_v1/statistical_audit.json`.
  - Decision: `POSITIVE_BUT_NOT_STATISTICALLY_CONFIRMED`.
  - Bootstrap ROI 5th percentile: `14.00%`.
  - Bootstrap positive ROI probability: `1.0`.
  - Sign-flip p-value: `0.226`.
  - Rejection reasons:
    - `bets<minimum`.
    - `active_months<minimum`.
    - `sign_flip_p_value>0.05`.

Interpretation:

- Ranking by strongest real-EV lower bound improved drawdown behavior versus the 15-bet unranked probe.
- It did so by reducing the sample to only `9` bets and `2` active months, so this is not yet a reusable money allocation algorithm.
- The current best real-EV research lead is now:
  - draw-only;
  - market-anchored real EV;
  - draw-specific features;
  - daily top-1 ranked candidate.
- But it remains below the evidence gate. The next step is not to deploy it; it is to broaden the historical/official-SP sample and see whether the same ranked draw signal can reach at least `50` bets and `6` active months while keeping drawdown below profit.

Four-Source I2 Band Recheck:

- Motivation:
  - After the real-EV fix, the weak-team/longshot model edge was deliberately compressed.
  - The main remaining historical candidate was the I2 market-bias draw family, so it was rerun under stricter source diversity instead of assuming the old `[2.8,3.5)` band was still reliable.
- Code:
  - `scripts/market_bias_i2_band_grid_search.py` now caches `build_market_frame(...)` once per odds source before evaluating candidate bands.
  - This does not change the validation logic; it removes repeated data construction so four-source band checks can finish in a usable time.
- Command:
  - `python scripts/market_bias_i2_band_grid_search.py --odds-sources AVG_OPEN,AVG_CLOSE,B365_OPEN,B365_CLOSE --min-low 2.7 --max-low 2.9 --min-width 0.4 --max-width 0.7 --step 0.1 --top-n 20 --output-dir reports/market_bias_i2_band_grid_search_four_sources_current`

Four-source grid result:

| Band | Passed Windows | Source Passes | Total Bets | Combined ROI | Worst Source ROI | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `[2.70,3.30)` | 8 / 24 | 3 / 4 | 2067 | 3.55% | -2.31% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `[2.80,3.20)` | 7 / 24 | 2 / 4 | 1054 | 8.43% | -12.07% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `[2.70,3.20)` | 6 / 24 | 3 / 4 | 971 | 10.33% | -13.13% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `[2.90,3.30)` | 6 / 24 | 3 / 4 | 1853 | 4.30% | -2.93% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `[2.80,3.30)` | 6 / 24 | 2 / 4 | 1987 | 4.18% | -0.99% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |
| `[2.80,3.50)` | 3 / 24 | 2 / 4 | 2169 | 1.57% | -0.52% | `RESEARCH_ONLY_UNSTABLE_WINDOWS` |

Settlement-aware portfolio spot checks, daily limit `100`, max single stake `10`:

| Rule / Source | Bets | Profit | ROI | Max DD | Month Balance | Season Balance | Verdict |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| `[2.70,3.30)` / AVG_OPEN | 206 | -13.10 | -0.64% | 366.50 | 3 / 4 | 2 / 1 | Rejected for real-money use |
| `[2.70,3.30)` / B365_CLOSE | 417 | +287.90 | 6.90% | 156.50 | 11 / 6 | 4 / 0 | Research-only; source-dependent |
| `[2.80,3.20)` / AVG_OPEN | 246 | +372.30 | 15.13% | 123.90 | 10 / 3 | 2 / 1 | Rejected for production: 2025-26 lost `-72.20` |

Interpretation:

- The four-source recheck weakens the I2 draw thesis. It remains a useful shadow/research candidate, but it is not a deployable daily investment algorithm.
- The apparent best bands are source-dependent. `[2.70,3.30)` is positive on B365_CLOSE but negative on AVG_OPEN. `[2.80,3.20)` has high AVG_OPEN ROI but fails the latest-season check.
- This reinforces the current policy: keep market-bias rules in shadow/prospective validation and do not convert them into production staking until Chinese official-SP samples confirm the edge.

Feature-Enriched I2 Scorer Recheck:

- Motivation:
  - The hand-built odds bands are too source-dependent.
  - The better algorithmic direction is a market-anchored feature residual scorer: start from market probability, then let a ridge model learn a small bounded residual from pre-match features.
- Code:
  - `scripts/feature_enriched_candidate_filter.py` now reports a hard `stability_verdict` for each configuration.
  - The gate requires enough bets, positive ROI, drawdown below profit, more positive than negative months and seasons, non-negative latest season, enough latest-season bets, and active rolling-window pass rate at least `0.60`.
  - This prevents high total ROI from being treated as deployable when recent-season or rolling-window evidence is weak.
- Command:
  - `python scripts/feature_enriched_candidate_filter.py --formal-i2-only --odds-sources AVG_OPEN,AVG_CLOSE --output-dir reports/feature_enriched_market_anchored_i2_formal_open_close_current`

Formal I2 feature-scorer result:

| Config | Bets | Profit | ROI | Max DD | Months | Seasons | Latest Season | Active Pass Rate | Verdict |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | --- |
| AVG_OPEN / train30 / EV >= 2% / top1 | 334 | +625.70 | 18.73% | 110.00 | 25 / 15 | 4 / 0 | +225.70 | 0.6667 | `SHADOW_READY_RESEARCH_CANDIDATE` |
| AVG_CLOSE / train30 / EV >= 2% / top1 | 335 | +439.90 | 13.13% | 115.80 | 21 / 19 | 4 / 0 | +203.20 | 0.5000 | `RESEARCH_ONLY_UNSTABLE` |

Exported scorer:

- Path: `reports/feature_enriched_market_anchored_i2_avg_open_scorer_current/scorer.json`.
- Training window: `2023-12-01` through `2026-05-23`.
- Training rows: `1074`.
- Strategy label: `AVG_OPEN_rulesi2_draw_2p8_3p5_train30_n120_ev0p02_top1_ridge10_cap0.08`.

Official-SP checks:

| Report | Scanned / Snapshots | Scored | Selected | Decision / Blocker |
| --- | ---: | ---: | ---: | --- |
| `reports/profit_scorer_official_pool_avg_open_current/summary.json` | 140 current official matches | 0 | 0 | Current pool has no usable I2 scorer candidates |
| `reports/profit_scorer_official_sp_validation_avg_open_current/summary.json` | 49 opening snapshots, 30 settled | 0 | 0 | `OFFICIAL_SP_PROSPECTIVE_BLOCKED` |

Main blockers:

- `league_not_i2`: current official pool is mostly World Cup / international / Nordic / Asian leagues, not Italy Serie B.
- `draw_sp_outside_[2.8,3.5)`: many official snapshots do not fall into the frozen I2 draw band.
- Some current official matches still lack live feature columns such as `lambda_home`, `lambda_away`, and weighted team history fields.

Interpretation:

- The AVG_OPEN feature-enriched I2 scorer is the strongest current historical research candidate because it beats the raw hand-built band on stability gates.
- It is still not a live money allocation algorithm, because official-SP prospective validation has zero selected settled samples.
- The practical next step is not to bet it immediately; it is to keep collecting official-SP snapshots until an actual I2-style pool appears, while separately searching a similarly feature-enriched scorer for the leagues that are present in the Chinese official pool.

Current Official-Pool Domain Expansion:

- Problem:
  - The current official pool is dominated by World Cup, FIN, SWE, KOR, and international fixtures.
  - I2 has the strongest historical scorer but is not present, so the system must not force that scorer onto unrelated leagues.
- Code:
  - `football_agents/official_pool_research.py` now maps `瑞超` / Swedish Allsvenskan to `SWE`.
  - `football_agents/profit_data_domain_readiness.py` now treats `SWE` as a known evidence domain.
  - `scripts/official_pool_market_anchored_research.py` now supports `SWE` anchored specs and a `--fast` mode for one representative market-anchored feature residual configuration per rule.
  - The official-pool research script now uses the same hard stability verdict family as the feature-enriched I2 scorer.
- Command:
  - `python scripts/official_pool_market_anchored_research.py --leagues SWE --odds-sources AVG_CLOSE,MAX_CLOSE --first-month 2016-01 --last-month 2025-12 --fast --output-dir reports/official_pool_market_anchored_research_swe_current_fast`

SWE result:

| Rule / Source | Bets | Profit | ROI | Max DD | Months | Seasons | Latest Season | Active Pass Rate | Decision |
| --- | ---: | ---: | ---: | ---: | --- | --- | ---: | ---: | --- |
| SWE away odds `[2.2,2.8)` / AVG_CLOSE | 206 | +262.10 | 12.72% | 145.00 | 37 / 29 | 6 / 5 | +39.90 from 18 bets | 0.4211 | `REJECT_RESEARCH_GATES` |
| SWE away odds `[2.2,2.8)` / MAX_CLOSE | 211 | +261.00 | 12.37% | 250.40 | 34 / 27 | 7 / 4 | +41.70 from 15 bets | 0.3158 | `REJECT_RESEARCH_GATES` |
| SWE home market probability `[0.55,1.00]` / MAX_CLOSE | 322 | +48.40 | 1.50% | 92.50 | 39 / 31 | 7 / 4 | +3.30 from 14 bets | 0.2105 | `REJECT_RESEARCH_GATES` |

Interpretation:

- SWE is now correctly recognized as a current official-pool domain with historical odds.
- The best-looking SWE candidate has real positive historical profit, but it fails the hard stability gate because active rolling-window pass rate is below `0.60` and latest-season sample is below 20 bets.
- This is a useful near-miss, not a deployable algorithm. It should not be converted into daily 100 allocation until a stricter or broader SWE model improves rolling-window stability.
- Updated official-pool planner:
  - World Cup: rejected by tournament holdout.
  - FIN: rejected by prior market-bias/residual gates.
  - SWE: rejected by current feature hard gates.
  - KOR: unmapped / no local historical 1X2 odds domain yet.
  - International: odds history missing.

True-EV broad-domain recheck:

- Purpose:
  - Move away from the weak-team positive-EV artifact by searching large, odds-backed domains for signals that survive cross-source prices and rolling allocation windows.
  - Treat diagnostic positives as hypotheses only. A rule is not true EV unless it survives cross-source validation, no-lookahead walk-forward, settlement-aware daily staking, and later official-SP prospective validation.
- Code:
  - `scripts/true_ev_research_summary.py` summarizes discovery, cross-source candidate screens, and multi-window reports into one deployment decision.
- First-pass discovery:
  - Output: `reports/batch_profit_domain_discovery_true_ev_current/summary.json`.
  - Domains scanned: `ARG`, `USA`, `BRA`, `MEX`, `ROU`.
  - All five had diagnostic hits, but these are not enough for allocation.
- Cross-source screens:

| Domain | Best surviving rule | Screen result | Main rejection reason |
| --- | --- | --- | --- |
| ARG | `home market_prob [0.20,0.28)` | `REJECTED_BY_CROSS_SOURCE_SCREEN` | only 27 combined portfolio bets; PS_CLOSE negative |
| USA | `home odds [2.2,2.8)` | `REJECTED_BY_CROSS_SOURCE_SCREEN` | combined ROI `-3.39%`; PS_CLOSE `-18.85%`; sample too small |
| BRA | none | `NO_SURVIVING_RULE_AFTER_RECENT_FORM_FILTER` | diagnostic positives failed recency/specificity filters |
| MEX | none | `NO_SURVIVING_RULE_AFTER_RECENT_FORM_FILTER` | diagnostic positives failed recency/specificity filters |
| ROU | none | `NO_SURVIVING_RULE_AFTER_RECENT_FORM_FILTER` | diagnostic positives failed recency/specificity filters |

- USA rolling 12-month check:
  - Report: `reports/market_bias_multi_window_usa_true_ev_current/summary.json`.
  - Candidate: `USA home odds [2.2,2.8)`.
  - Total repeated-window bets: `214`.
  - Combined ROI: `-3.39%`.
  - Active pass rate: `0.00`.
  - Source pass rate: `0.00`.
  - Decision: `REJECT_UNSTABLE`.
- Consolidated true-EV summary:
  - Report: `reports/true_ev_research_summary_current/summary.json`.
  - Decision: `NO_TRUE_EV_CANDIDATE_FOUND`.

Interpretation:

- This is a useful negative result. It shows the stricter process is filtering exactly the kind of false EV we were worried about: impressive local slices, sparse high-ROI samples, and signals that disappear when the available price source changes.
- The next search should not loosen gates on these domains. It should either:
  - expand to the next large search-ready domains (`POL`, `NOR`, `RUS`, `DNK`, `CHN`, and classic European league codes), or
  - move from coarse market-bucket rules to a feature-residual model, while keeping the same cross-source and rolling-window gates.

True-EV broad-domain recheck, next 5 domains:

- Purpose:
  - Continue the same gate on the next largest search-ready domains rather than loosening failed thresholds.
  - Domains: `POL`, `NOR`, `RUS`, `DNK`, `CHN`.
- First-pass discovery:
  - Output: `reports/batch_profit_domain_discovery_true_ev_next5_current/summary.json`.
  - Domains with diagnostic hits: `4 / 5`.
  - `POL` had no diagnostic hits.
  - Notable surface signals:
    - `RUS home odds [2.2,2.8)`: 693 diagnostic bets, +53.55 units, 7.73% ROI, latest month positive.
    - `DNK odds [2.8,3.5) / market_prob [0.20,0.28)`: 765 diagnostic bets, +42.46 units, 5.55% ROI.
    - `CHN draw market_prob [0.28,0.34)`: 649 diagnostic bets, +86.48 units, 13.33% ROI, but latest month negative.
- Cross-source screens:

| Domain | Best surviving rule | Screen result | Main rejection reason |
| --- | --- | --- | --- |
| POL | none | `NO_SURVIVING_RULE_AFTER_RECENT_FORM_FILTER` | no diagnostic hits |
| NOR | `home odds [1.8,2.2)` | `REJECTED_BY_CROSS_SOURCE_SCREEN` | combined ROI `-19.96%`; all sources negative |
| RUS | `home odds [2.2,2.8)` / tested separately | `REJECTED_BY_CROSS_SOURCE_SCREEN` | no rule passed; surface positives disappear after no-lookahead selection |
| DNK | `draw odds [2.8,3.5)` | `REJECTED_BY_CROSS_SOURCE_SCREEN` | combined ROI `-7.38%`; AVG/MAX close negative |
| CHN | none | `NO_SURVIVING_RULE_AFTER_RECENT_FORM_FILTER` | strongest draw signal failed recent-form filter |

- RUS rolling 12-month check:
  - Report: `reports/market_bias_multi_window_rus_true_ev_next5_current/summary.json`.
  - Representative tested candidate: `RUS home odds [2.2,2.8)`.
  - Total repeated-window bets: `214`.
  - Combined ROI: `-12.88%`.
  - Active pass rate: `0.00`.
  - Source pass rate: `0.00`.
  - Worst source ROI: `-20.00%`.
  - Decision: `REJECT_UNSTABLE`.
- Consolidated true-EV summary:
  - Report: `reports/true_ev_research_summary_next5_current/summary.json`.
  - Decision: `NO_TRUE_EV_CANDIDATE_FOUND`.

Interpretation:

- This second batch confirms that the current coarse market-bucket approach is mostly discovering in-sample price-shape artifacts, not reusable betting edge.
- The most tempting candidates are exactly where the gate is useful:
  - `CHN draw` has impressive full-period ROI but fails the recent-form filter.
  - `RUS home [2.2,2.8)` has strong diagnostic ROI but becomes negative under no-lookahead cross-source validation.
- Next work should prioritize a model-based residual scorer over more hand bucket widening, unless scanning the remaining classic European domains is needed to rule out obvious coarse signals.

Feature-Residual True-EV Update:

- Problem:
  - Live EV was too often positive on weak teams and negative on strong teams.
  - That pattern usually means the model is over-trusting its own residual against the market. It treats high odds as cheap probability, but the bookmaker/market prior is usually the stronger estimate.
- Code:
  - `football_agents/real_ev.py` now uses a stricter real-probability anchor:
    - lower model residual retention: `0.08 + 0.28 * reliability`;
    - positive residuals on non-favorite home/away teams are discounted before EV;
    - longshot positive residuals are still discounted;
    - downside residuals on the market favorite are capped so the model cannot casually turn the strong side into negative EV.
  - Diagnostics now expose:
    - `underdog_penalties`;
    - `favorite_downside_caps`;
    - warnings such as `away underdog positive residual discounted`.
- Tests:
  - `tests/test_real_ev.py::test_underdog_positive_residual_is_discounted_before_ev`.
  - `tests/test_real_ev.py::test_market_favorite_downside_residual_is_capped`.
  - Related true-odds/workflow tests remain passing.

Focused feature-residual research:

- Fast next-domain run:
  - Report: `reports/official_pool_market_anchored_research_true_ev_next5_fast_current/summary.json`.
  - Best near-miss: `DNK draw odds [2.8,3.5)` on `PS_CLOSE`.
  - 268 bets, profit `+660.50`, ROI `24.65%`, max drawdown `121.10`.
  - Rejected because latest-season bets `<20` and active pass rate `<0.60`.
- Focused DNK draw grid:
  - Report: `reports/official_pool_market_anchored_research_dnk_draw_grid_current/summary.json`.
  - Best row: `AVG_CLOSE_rulesdnk_draw_odds2p8_3p5_train30_n80_ev0p02_top1_ridge10_cap0.08`.
  - 364 bets, profit `+613.60`, ROI `16.86%`, max drawdown `140.00`.
  - Rolling windows: active pass rate `0.55`.
  - Decision: `REJECT_RESEARCH_GATES`, reason `active_pass_rate<0.6`.

Interpretation:

- The old weak-team EV problem is now addressed at the EV probability layer, not by hiding results in Critic.
- The system should now require a model edge to survive market anchoring before it becomes real EV.
- DNK draw is a genuine research lead, but it is still not live allocation because it narrowly fails the active rolling-window gate. This is exactly the sort of candidate to keep in shadow/research, not to force into daily money allocation yet.

DNK Draw Rolling Quality Filter:

- Problem:
  - `DNK draw odds [2.8,3.5)` was the strongest non-World-Cup near-miss: high total ROI, positive latest season, but active rolling-window pass rate below the required `0.60`.
  - Full-sample slicing suggested the raw candidate was weaker when `abs_form_points_diff <= 0.6` and stronger in moderate form-gap ranges, but a full-sample filter would be leakage.
- Code:
  - Added `scripts/rolling_candidate_quality_filter.py`.
  - It reads an existing no-leak selected-candidate file and, for each month, uses only prior selected-candidate outcomes to decide which feature buckets are allowed in the current month.
  - It reports the same settlement-aware daily portfolio, rolling-window pass rate, season results, and hard-gate decision.
- Tests:
  - `tests/test_rolling_candidate_quality_filter.py`.
  - The tests verify that bucket selection uses prior profitability and does not use the current month to select the current month bucket.
- Commands:
  - `python scripts/rolling_candidate_quality_filter.py --input reports/official_pool_market_anchored_research_dnk_draw_grid_current/selected.csv --first-month 2016-01 --last-month 2026-06 --fast --output-dir reports/rolling_candidate_quality_filter_dnk_draw_fast_current`
  - `python scripts/rolling_candidate_quality_filter.py --input reports/official_pool_market_anchored_research_dnk_draw_grid_current/selected.csv --first-month 2020-01 --last-month 2026-06 --fast --output-dir reports/rolling_candidate_quality_filter_dnk_draw_fast_recent_current`

Results:

| Experiment | Best Filter | Bets | Profit | ROI | Max DD | Seasons | Latest Season | Active Pass Rate | Decision |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- |
| Full window 2016-2026 | `train36_abs_form_points_bucket_n20_profit1_roi0p05_pm3_ev0p02` | 206 | +446.70 | 21.68% | 90.00 | 9 / 0 | +108.20 from 27 bets | 0.3333 | `RESEARCH_ONLY_UNSTABLE` |
| Recent window 2020-2026 | same | 169 | +354.10 | 20.95% | 90.00 | 6 / 1 | +108.20 from 27 bets | 0.5000 | `RESEARCH_ONLY_UNSTABLE` |

Interpretation:

- Rolling bucket quality filtering improves headline ROI and drawdown versus the unfiltered DNK near-miss, but it does not solve the stability requirement.
- The recent-window result is better (`0.50` active pass rate), but still below `0.60`.
- This is not a reason to relax the gate. It is evidence that DNK draw has a promising but regime-sensitive signal.
- DNK should remain research-only until a filter passes active rolling windows and then survives cross-source and official-SP prospective validation.

World Cup Real-EV Residual Walk-Forward:

- Problem:
  - Prior World Cup work used tournament/bucket portfolio validation. That was useful, but it did not run the same real-EV residual model used by the newer live decision path.
  - `scripts/walk_forward_residual_strategy.py` previously loaded only season directories such as `2425`; it could not load `data/historical_csv/football-data/new/WORLD_CUP.csv`.
- Code:
  - `load_season_matches()` now accepts:
    - normal season directories such as `2425`;
    - direct CSV paths;
    - single-file domains under `data/historical_csv/football-data/new/`, e.g. `WORLD_CUP`.
  - Added sparse event profiles:
    - `world_cup_sparse`: draw-only, research-only, 120-month training window, 18-month validation window, minimum 150 train rows and 25 validation rows.
    - `world_cup_sparse_all`: home/draw/away, research-only, stricter validation minimum of 5 bets.
    - `world_cup_sparse_probe`: home/draw/away, research-only probe with only 1 validation bet required; this exists only to test whether loosening the validation gate creates real out-of-sample value.
  - Monthly reports now include `evaluated_configs` and `best_failed_validation` when no stable config is selected.
- Commands:
  - `python scripts/walk_forward_residual_strategy.py --seasons WORLD_CUP --first-month 2024-03 --months 28 --profile world_cup_sparse --output-dir reports/residual_walk_forward_world_cup_sparse_real_ev_current`
  - `python scripts/walk_forward_residual_strategy.py --seasons WORLD_CUP --first-month 2024-03 --months 28 --profile world_cup_sparse_all --output-dir reports/residual_walk_forward_world_cup_sparse_all_real_ev_current`
  - `python scripts/walk_forward_residual_strategy.py --seasons WORLD_CUP --first-month 2024-03 --months 28 --profile world_cup_sparse_probe --output-dir reports/residual_walk_forward_world_cup_sparse_probe_real_ev_current`

Results:

| Profile | Scope | Validation Strictness | Bets | Profit | ROI | Invested Months | Main Result |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `world_cup_sparse` | Draw only | 3 validation bets | 0 | 0.00 | 0.00% | 1 | selected once, but test month had no bet |
| `world_cup_sparse_all` | Home/draw/away | 5 validation bets | 0 | 0.00 | 0.00% | 0 | no stable validation config |
| `world_cup_sparse_probe` | Home/draw/away | 1 validation bet | 1 | -1.00 | -100.00% | 4 | only out-of-sample bet lost |

Probe bet:

- Date: `2025-11-15`.
- Match: Greece vs Scotland.
- Pick: draw.
- Actual: home.
- True probability: `0.325690`.
- Model probability before real-EV anchor: `0.422869`.
- Odds: `3.18`.
- Real lower EV after uncertainty: `-0.001139`.
- Model lower EV before true-EV anchoring: `0.307890`.
- Result: stake `1.00`, profit `-1.00`.

Interpretation:

- The real-EV anchor did exactly what it should: the raw model saw a large draw edge, but the anchored true probability reduced it close to break-even.
- Requiring normal validation stability leads to no deployable World Cup bets.
- Loosening validation to a single prior winning bet produces one sample-out bet and it loses. That is evidence against relaxing thresholds for World Cup allocation.
- Current World Cup status remains rejected for money allocation. Keep the data for model calibration and future research, but do not route daily 100 allocation into World Cup from current evidence.

Legacy Residual Promotion Recheck Under Current Real-EV Anchor:

- Problem:
  - An older five-season residual report (`reports/residual_walk_forward_5season_strict_v1/summary.json`) showed a small positive walk-forward result and `PROMOTE_TO_LARGER_SHADOW`.
  - That report was generated before the stricter real-EV market anchor, underdog residual discount, and favorite downside cap were added.
  - It must therefore not be treated as evidence that the current live EV engine has found deployable edge.
- Command:
  - `python scripts/walk_forward_residual_strategy.py --seasons 2122,2223,2324,2425,2526 --first-month 2023-08 --months 34 --profile strict --output-dir reports/residual_walk_forward_5season_strict_current_real_ev_recheck`
- Result:
  - Method: `nested monthly walk-forward real-EV market anchor + residual isotonic + league shrinkage + constrained Kelly`.
  - Bets: `0`.
  - Profit: `0.00`.
  - Invested months: `0 / 34`.
  - Decision: `NEED_MORE_DATA`.
  - Main reason: no monthly configuration passed the current validation gate after the real-EV anchor was applied.
- Registry / allocation change:
  - `football_agents/profit_strategy_registry.py` now reads the latest I2 profit scorecard when building the strategy package.
  - If the scorecard says `RESEARCH_ONLY_UNSTABLE_WINDOWS` and `recommended_for_shadow=false`, the package status is downgraded instead of returning the old `PROMOTE_TO_OFFICIAL_SP_SHADOW_VALIDATION` label.
  - `football_agents/profit_allocation_readiness.py` now treats `RESEARCH_ONLY*` or `recommended_for_shadow=false` packages as not historically supported for daily allocation.

Interpretation:

- This is an intentional false-positive cleanup. The system should prefer abstaining over manufacturing positive EV from an older model family.
- Historical profit remains useful for research triage, but current money allocation requires the edge to survive the latest real-EV anchor, multi-window gate, and official-SP prospective validation.

True-EV Broad-Domain Recheck, English / European Batch:

- Purpose:
  - Continue the true-EV search after World Cup, Nordic, and broad new-domain candidates failed.
  - This batch intentionally included stronger-team / market-favorite structures, not only weak-team high-odds outcomes, to test whether the system can find an edge that does not reduce to "bet underdogs".
- Domain readiness:
  - Current report: `reports/profit_data_domain_readiness_current/summary.json`.
  - World Cup remains `REJECTED_BY_EXISTING_STABILITY_GATES`.
  - `INTERNATIONAL_ODDS_API.csv` still has no usable 1X2 odds rows, so it cannot validate EV.
- Discovery batch B:
  - Report: `reports/batch_profit_domain_discovery_true_ev_next5b_current/summary.json`.
  - Domains: `E1`, `E3`, `E2`, `IRL`, `SWZ`.
  - Diagnostic hits: `4 / 5`.
  - Best surfaces:
    - `E2` low-odds / high-market-probability favorites.
    - `SWZ` away favorite / market-probability structures.
  - Cross-source summary: `reports/true_ev_research_summary_next5b_current/summary.json`.
  - Decision: `NO_TRUE_EV_CANDIDATE_FOUND`.
- Discovery batch C:
  - Report: `reports/batch_profit_domain_discovery_true_ev_next5c_current/summary.json`.
  - Domains: `AUT`, `SP2`, `I1`, `E0`, `F2`.
  - Diagnostic hits: `4 / 5`.
  - Best surfaces:
    - `I1 away market_favorite`: cross-source screen total 189 bets, +164.00, ROI `8.68%`, but every source failed the screen; four sources had fewer than 100 bets, and MAX prices failed ROI/month/drawdown checks.
    - `AUT away [1.8,2.2)`: diagnostic positive, but no no-lookahead cross-source portfolio bets.
    - `E0 home [2.2,2.8)`: 111 cross-source portfolio bets, ROI `-11.72%`.
  - Multi-window I1 report: `reports/market_bias_multi_window_i1_true_ev_next5c_current/summary.json`.
  - Cross-source summary: `reports/true_ev_research_summary_next5c_current/summary.json`.
  - Decision: `NO_TRUE_EV_CANDIDATE_FOUND`.

I1 near-miss details:

| Candidate | Screen Bets | Screen ROI | Multi-window Bets | Multi-window ROI | Active Pass Rate | Source Pass Rate | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `I1 away market_favorite` | 189 | 8.68% | 149 | -7.56% | 0.0000 | 0.0000 | `REJECT_UNSTABLE` |
| `I1 away [1.0,1.8)` | 88 | -2.68% | 123 | -2.63% | 0.0000 | 0.0000 | `REJECT_UNSTABLE` |

Interpretation:

- The stronger-team / favorite direction is not automatically profitable either. It can look good in a diagnostic slice, but no-lookahead rolling selection and cross-source validation remove the apparent edge.
- This reinforces the current true-EV rule: do not allocate the daily 100 budget from diagnostic ROI, and do not treat a combined positive cross-source screen as enough when each source has low sample or unstable windows.
- The next useful search should be either:
  - continue through the remaining search-ready domains (`T1`, `F1`, `B1`, `D2`, `P1`, `D1`, `N1`, `G1`, `SC0`), or
  - move beyond coarse market-bucket rules into a feature-residual scorer for the best near-miss shapes, while preserving the same cross-source and multi-window gates.

True-EV Broad-Domain Recheck, Batch D:

- Purpose:
  - Test another block of search-ready domains, including a stronger-team / favorite-heavy shape, under the stricter true-EV standard.
  - This batch is especially useful for diagnosing false EV caused by assuming we can obtain the most favorable market price.
- Discovery batch D:
  - Report: `reports/batch_profit_domain_discovery_true_ev_next5d_current/summary.json`.
  - Domains: `T1`, `F1`, `B1`, `D2`, `P1`.
  - Diagnostic hits: `5 / 5`.
  - Best diagnostic surface: `T1 market_prob [0.55,1.00]`.
- Cross-source T1 screen:
  - Report: `reports/market_bias_candidate_screen_t1_true_ev_next5d_current/summary.json`.
  - Best rule: `league|market_prob_bucket=T1|[0.55,1.00]`.
  - Combined result: 1,037 portfolio bets, `+525.40`, ROI `5.07%`.
  - Passing sources: `MAX_CLOSE`, `MAX_OPEN`, `B365_OPEN`.
  - Failing sources: `AVG_OPEN`, `AVG_CLOSE`, `B365_CLOSE`.
  - Reason for rejection: the rule depends too much on best/early prices. Average and closing prices are near-flat or negative, which means the apparent edge is not robustly obtainable.
- Frozen T1 multi-window check:
  - Report: `reports/market_bias_multi_window_t1_true_ev_next5d_frozen_current/summary.json`.
  - Best candidate: `t1-market-prob-0p55-1p00`.
  - Total result: 3,889 bets, `+1870.10`, ROI `4.81%`.
  - Active pass rate: `0.4286`, below the required `0.60`.
  - Worst window ROI: `-46.20%`.
  - Source weakness: `AVG_CLOSE` ROI `-1.46%`, `B365_CLOSE` ROI `-2.11%`, `AVG_OPEN` ROI only `0.15%`.
  - Decision: `RESEARCH_ONLY_UNSTABLE_WINDOWS`.
- Other batch-D screens:
  - `P1`: no cross-source rule passed; best screen had zero portfolio bets.
  - `B1`: no cross-source rule passed; best combined ROI only `1.23%`.
  - `F1`: no cross-source rule passed.
  - `D2`: no cross-source rule passed.
- Summary report:
  - `reports/true_ev_research_summary_next5d_current/summary.json`.
  - Decision: `NO_TRUE_EV_CANDIDATE_FOUND`.

Interpretation:

- T1 is the clearest example so far of why the new true-EV definition must include price availability. It looks profitable under maximum/open prices, but it loses the signal under realistic average/closing prices.
- This directly addresses the earlier "weak teams always have positive EV" concern: the system must not treat a model-market probability gap as real EV unless it survives cross-source price tests, no-lookahead windows, and settlement-aware staking.
- Batch D should not feed the live daily 100 allocation. Its useful contribution is diagnostic: it identifies price-source sensitivity as a major false-EV mechanism.

True-EV Broad-Domain Recheck, Batch E:

- Purpose:
  - Finish the current readiness-ranked search block after batch D.
  - Test the remaining large classic domains with the same true-EV standard.
- Discovery batch E:
  - Report: `reports/batch_profit_domain_discovery_true_ev_next4e_current/summary.json`.
  - Domains: `D1`, `N1`, `G1`, `SC0`.
  - Diagnostic hits: `4 / 4`.
  - Best diagnostic surfaces:
    - `N1 draw [5.0,7.0)`: 229 diagnostic bets, `+46.50`, ROI `20.31%`.
    - `G1 draw [2.8,3.5) / market_prob [0.28,0.34)`: 552 diagnostic bets, `+18.69`, ROI `3.39%`.
    - `SC0 home [1.0,1.8)`: 317 diagnostic bets, `+15.63`, ROI `4.93%`.
    - `D1 draw / market_prob [0.20,0.28)`: 1,084 diagnostic bets, `+67.85`, ROI `6.26%`.
- Cross-source screens:
  - Summary: `reports/true_ev_research_summary_next4e_current/summary.json`.
  - Decision: `NO_TRUE_EV_CANDIDATE_FOUND`.
  - `D1`: best rule `league|market_prob_bucket=D1|[0.20,0.28)` had combined ROI `5.67%`, but only 86 best-source portfolio bets and drawdown greater than profit.
  - `N1`: best rule `league|odds_bucket=N1|[4.0,5.0)` had combined ROI `18.98%`, but failed every validation source; B365 open was negative and average sources lacked enough usable bets.
  - `G1`: best rule `league|outcome|odds_bucket=G1|draw|[2.8,3.5)` had combined ROI `15.43%`, but failed every validation source; B365 close was `-16.32%` and most sources had fewer than 100 bets.
  - `SC0`: best surviving screen was negative (`-45.71%`) and rejected.

Interpretation:

- N1 and G1 are tempting research leads, but they are not true EV yet. Their apparent edge is too concentrated in sparse windows or favorable price sources.
- This reinforces the updated algorithmic rule: a profitable-looking bucket is not allowed into live staking unless it survives realistic available prices and enough settled no-lookahead bets.
- The current live money policy should remain conservative: no forced daily allocation from D1/N1/G1/SC0.

Multi-Source Discovery Upgrade:

- Problem:
  - The earlier discovery flow could start from one attractive price source and only later reject it during cross-source validation.
  - That is useful, but it wastes search effort on rules that were probably price-source artifacts from the start.
- Code:
  - Added `scripts/multi_source_market_bias_discovery.py`.
  - It runs market-bias diagnostics across multiple odds sources first, then keeps only rules that pass source-level discovery checks in at least `N` sources.
  - Default sources: `B365_OPEN`, `AVG_OPEN`, `MAX_OPEN`, `B365_CLOSE`, `AVG_CLOSE`, `MAX_CLOSE`.
  - The script writes:
    - `market_candidates.csv`;
    - `market_bias.csv`, containing only multi-source discovery rows;
    - `market_bias_with_sources.json`, preserving per-source evidence;
    - `summary.json`.
- Tests:
  - `tests/test_multi_source_market_bias_discovery.py`.
  - The tests verify that a single-source positive rule is rejected when `min_sources=2`, and that the optional latest-period filter can reject stale candidates.
- Command:
  - `python scripts/multi_source_market_bias_discovery.py --seasons 2122,2223,2324,2425,2526 --min-samples 100 --min-active-months 12 --max-combo-size 3 --min-sources 3 --min-source-roi-pct 3 --output-dir reports/multi_source_market_bias_discovery_all_classic_current`
- Discovery result:
  - Raw diagnostic rows: `1306`.
  - Multi-source robust discovery rows: `37`.
  - Strongest discovery rows:
    - `I1 away [1.0,1.8)`: 6 / 6 discovery sources, 1,395 source-combined diagnostic bets, ROI `9.70%`.
    - `I1 away market_prob [0.55,1.00]`: 6 / 6 discovery sources, ROI `9.13%`.
    - `SP1 away market_prob [0.42,0.55)`: 6 / 6 discovery sources, ROI `11.27%`.
    - `G1 draw market_prob [0.28,0.34)`: 6 / 6 discovery sources, ROI `7.93%`.
- No-lookahead cross-source screen:
  - Command:
    - `python scripts/market_bias_candidate_screen.py --diagnostics-csv reports/multi_source_market_bias_discovery_all_classic_current/market_bias.csv --no-include-default-rule --seasons 2122,2223,2324,2425,2526 --first-month 2022-08 --last-month 2026-05 --validation-odds-source B365_OPEN --validation-odds-source AVG_OPEN --validation-odds-source MAX_OPEN --validation-odds-source B365_CLOSE --validation-odds-source AVG_CLOSE --validation-odds-source MAX_CLOSE --top-n 12 --output-dir reports/market_bias_candidate_screen_multi_source_classic_current`
  - Summary: `reports/true_ev_research_summary_multi_source_classic_current/summary.json`.
  - Candidate source rows screened: `72`.
  - Individual source passes: `4`.
  - Rules passing all validation sources: `0`.
  - Decision: `NO_TRUE_EV_CANDIDATE_FOUND`.
  - Best rule after screening: `SP1 home [1.0,1.8)`, combined 461 portfolio bets, `+471.80`, ROI `10.23%`, but it passed only `MAX_CLOSE` and `MAX_OPEN`; B365/AVG open failed and the worst source ROI was `-4.76%`.

Interpretation:

- Multi-source discovery is a useful upgrade because it removes many single-source artifacts before walk-forward validation.
- However, discovery consistency is still not enough. The best remaining rules lose stability once month-by-month no-lookahead selection, settlement-aware staking, and realistic non-MAX prices are applied.
- The next algorithmic step should move beyond static market buckets into a time-aware feature scorer, but it must preserve this same rule: no live allocation without cross-source and rolling-window survival.
