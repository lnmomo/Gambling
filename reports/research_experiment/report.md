# Research Experiment Report

## Dataset Audit

- Files: 106
- Raw rows: 33364
- Usable rows: 33331
- Date range: 2021-07-23 to 2026-05-31
- Odds timing: pre_closing
- Exact odds timestamps: False

## Probability Metrics

| Model | N | Log Loss | Brier | RPS | Top-label ECE | Macro classwise ECE |
|---|---:|---:|---:|---:|---:|---:|
| market | 6592 | 0.995917 | 0.594612 | 0.201729 | 0.014830 | 0.011855 |
| dixon_coles | 6592 | 1.061428 | 0.640658 | 0.223687 | 0.033954 | 0.039132 |
| fixed_blend | 6592 | 1.002875 | 0.598926 | 0.203800 | 0.035139 | 0.028445 |
| proposed | 6592 | 0.995323 | 0.594443 | 0.201659 | 0.010626 | 0.008690 |
| ablation_no_calibration | 6592 | 0.995611 | 0.594505 | 0.201730 | 0.010214 | 0.009990 |
| ablation_no_league | 6592 | 0.995157 | 0.594292 | 0.201547 | 0.010417 | 0.007932 |
| closing_market_reference | 6592 | 0.993159 | 0.592631 | 0.200857 | 0.012938 | 0.012125 |

## Paired Bootstrap: Proposed Minus Baseline Log Loss

Negative values favor the proposed model.

| Baseline | Difference | 95% CI | P(proposed better) |
|---|---:|---:|---:|
| market | -0.000594 | [-0.002022, 0.000948] | 0.782 |
| dixon_coles | -0.066106 | [-0.074419, -0.057248] | 1.000 |
| fixed_blend | -0.007552 | [-0.010622, -0.004082] | 1.000 |
| ablation_no_calibration | -0.000288 | [-0.001333, 0.000771] | 0.691 |
| ablation_no_league | 0.000166 | [-0.000417, 0.000756] | 0.279 |
| closing_market_reference | 0.002164 | [-0.000172, 0.004603] | 0.038 |

## Interpretation Guardrails

- Closing market is a reference benchmark and is never a deployable pre-match input.
- A confidence interval crossing zero is not evidence of superiority.
- Betting ROI is intentionally excluded from model selection.
- CSV odds lack exact collection timestamps and are not described as guaranteed opening odds.
