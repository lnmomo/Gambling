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
| dixon_coles | 6592 | 1.066286 | 0.644158 | 0.225381 | 0.014833 | 0.033917 |
| hierarchical_dixon_coles | 6592 | 1.065799 | 0.643885 | 0.225276 | 0.018743 | 0.035806 |
| fixed_blend | 6592 | 1.003386 | 0.599250 | 0.203949 | 0.035797 | 0.028505 |
| multinomial_logit | 6592 | 1.008462 | 0.603586 | 0.205731 | 0.007575 | 0.009557 |
| random_forest | 6592 | 1.010955 | 0.605453 | 0.206651 | 0.014157 | 0.011767 |
| hist_gradient_boosting | 6592 | 1.011564 | 0.605624 | 0.206655 | 0.005754 | 0.009524 |
| proposed | 6592 | 0.995170 | 0.594241 | 0.201557 | 0.011706 | 0.009572 |
| ablation_no_features | 6592 | 0.995098 | 0.594250 | 0.201524 | 0.009185 | 0.007847 |
| ablation_no_calibration | 6592 | 0.995342 | 0.594281 | 0.201616 | 0.010244 | 0.009599 |
| ablation_no_league | 6592 | 0.994971 | 0.594070 | 0.201440 | 0.013814 | 0.009873 |
| closing_market_reference | 6592 | 0.993159 | 0.592631 | 0.200857 | 0.012938 | 0.012125 |

## Paired Bootstrap: Proposed Minus Baseline Log Loss

Negative values favor the proposed model.

| Baseline | Difference | 95% CI | P(proposed better) |
|---|---:|---:|---:|
| market | -0.000747 | [-0.002312, 0.000934] | 0.807 |
| dixon_coles | -0.071116 | [-0.079707, -0.061780] | 1.000 |
| hierarchical_dixon_coles | -0.070629 | [-0.079213, -0.061371] | 1.000 |
| fixed_blend | -0.008216 | [-0.011346, -0.004653] | 1.000 |
| multinomial_logit | -0.013291 | [-0.016854, -0.009729] | 1.000 |
| random_forest | -0.015785 | [-0.019826, -0.011532] | 1.000 |
| hist_gradient_boosting | -0.016394 | [-0.020426, -0.012006] | 1.000 |
| ablation_no_features | 0.000072 | [-0.000988, 0.001170] | 0.441 |
| ablation_no_calibration | -0.000172 | [-0.001151, 0.000862] | 0.618 |
| ablation_no_league | 0.000199 | [-0.000375, 0.000781] | 0.238 |
| closing_market_reference | 0.002011 | [-0.000419, 0.004525] | 0.060 |

## Interpretation Guardrails

- Closing market is a reference benchmark and is never a deployable pre-match input.
- A confidence interval crossing zero is not evidence of superiority.
- Betting ROI is intentionally excluded from model selection.
- CSV odds lack exact collection timestamps and are not described as guaranteed opening odds.
