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
| market | 6563 | 0.999345 | 0.597576 | 0.202818 | 0.010744 | 0.011428 |
| dixon_coles | 6563 | 1.020188 | 0.611794 | 0.209468 | 0.008656 | 0.009428 |
| hierarchical_dixon_coles | 6563 | 1.021049 | 0.612131 | 0.209633 | 0.017961 | 0.012404 |
| fixed_blend | 6563 | 1.001798 | 0.599207 | 0.203597 | 0.017055 | 0.012114 |
| multinomial_logit | 6563 | 1.012369 | 0.606279 | 0.206955 | 0.009163 | 0.007965 |
| random_forest | 6563 | 1.015621 | 0.608332 | 0.207583 | 0.014094 | 0.011689 |
| hist_gradient_boosting | 6563 | 1.016755 | 0.609146 | 0.207868 | 0.007102 | 0.010397 |
| proposed | 6563 | 0.998396 | 0.597308 | 0.202710 | 0.010188 | 0.010008 |
| ablation_no_features | 6563 | 0.998310 | 0.597161 | 0.202585 | 0.010842 | 0.011750 |
| ablation_no_calibration | 6563 | 0.999270 | 0.597848 | 0.202924 | 0.012688 | 0.008313 |
| ablation_no_league | 6563 | 0.998330 | 0.597195 | 0.202652 | 0.010574 | 0.007660 |
| closing_market_reference | 6563 | 0.996959 | 0.595975 | 0.201996 | 0.015612 | 0.015248 |

## Paired Bootstrap: Proposed Minus Baseline Log Loss

Negative values favor the proposed model.

| Baseline | Difference | 95% CI | P(proposed better) |
|---|---:|---:|---:|
| market | -0.000949 | [-0.002560, 0.000625] | 0.886 |
| dixon_coles | -0.021792 | [-0.026512, -0.016935] | 1.000 |
| hierarchical_dixon_coles | -0.022653 | [-0.027652, -0.017398] | 1.000 |
| fixed_blend | -0.003402 | [-0.005606, -0.001108] | 0.998 |
| multinomial_logit | -0.013973 | [-0.017779, -0.009850] | 1.000 |
| random_forest | -0.017225 | [-0.021478, -0.012775] | 1.000 |
| hist_gradient_boosting | -0.018359 | [-0.022709, -0.013889] | 1.000 |
| ablation_no_features | 0.000086 | [-0.000898, 0.001077] | 0.457 |
| ablation_no_calibration | -0.000874 | [-0.002279, 0.000538] | 0.891 |
| ablation_no_league | 0.000066 | [-0.000885, 0.001003] | 0.447 |
| closing_market_reference | 0.001437 | [-0.000933, 0.003856] | 0.115 |

## Interpretation Guardrails

- Closing market is a reference benchmark and is never a deployable pre-match input.
- A confidence interval crossing zero is not evidence of superiority.
- Betting ROI is intentionally excluded from model selection.
- CSV odds lack exact collection timestamps and are not described as guaranteed opening odds.
