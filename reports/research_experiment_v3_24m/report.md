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
| market | 13339 | 0.992956 | 0.592649 | 0.200982 | 0.013133 | 0.012117 |
| dixon_coles | 13339 | 1.012932 | 0.606479 | 0.207451 | 0.005678 | 0.009386 |
| hierarchical_dixon_coles | 13339 | 1.014453 | 0.607500 | 0.207824 | 0.012081 | 0.013422 |
| fixed_blend | 13339 | 0.995146 | 0.594217 | 0.201707 | 0.011929 | 0.011161 |
| multinomial_logit | 13339 | 1.005700 | 0.601511 | 0.205084 | 0.008896 | 0.007618 |
| random_forest | 13339 | 1.006699 | 0.602513 | 0.205560 | 0.005445 | 0.007431 |
| hist_gradient_boosting | 13339 | 1.009815 | 0.604400 | 0.206290 | 0.002976 | 0.010300 |
| proposed | 13339 | 0.992927 | 0.592810 | 0.200978 | 0.009656 | 0.011504 |
| ablation_no_features | 13339 | 0.993061 | 0.592836 | 0.200953 | 0.010261 | 0.012858 |
| ablation_no_calibration | 13339 | 0.992494 | 0.592482 | 0.200932 | 0.008162 | 0.008678 |
| ablation_no_league | 13339 | 0.992775 | 0.592678 | 0.200963 | 0.010130 | 0.009631 |
| closing_market_reference | 13339 | 0.989754 | 0.590401 | 0.199998 | 0.014981 | 0.013921 |

## Paired Bootstrap: Proposed Minus Baseline Log Loss

Negative values favor the proposed model.

| Baseline | Difference | 95% CI | P(proposed better) |
|---|---:|---:|---:|
| market | -0.000029 | [-0.001032, 0.000946] | 0.518 |
| dixon_coles | -0.020005 | [-0.023255, -0.016615] | 1.000 |
| hierarchical_dixon_coles | -0.021526 | [-0.024913, -0.017928] | 1.000 |
| fixed_blend | -0.002219 | [-0.003537, -0.000827] | 1.000 |
| multinomial_logit | -0.012773 | [-0.015222, -0.010043] | 1.000 |
| random_forest | -0.013772 | [-0.016698, -0.010894] | 1.000 |
| hist_gradient_boosting | -0.016888 | [-0.019921, -0.013681] | 1.000 |
| ablation_no_features | -0.000134 | [-0.000771, 0.000456] | 0.659 |
| ablation_no_calibration | 0.000433 | [-0.000485, 0.001318] | 0.163 |
| ablation_no_league | 0.000152 | [-0.000530, 0.000858] | 0.321 |
| closing_market_reference | 0.003173 | [0.001430, 0.004912] | 0.001 |

## Interpretation Guardrails

- Closing market is a reference benchmark and is never a deployable pre-match input.
- A confidence interval crossing zero is not evidence of superiority.
- Betting ROI is intentionally excluded from model selection.
- CSV odds lack exact collection timestamps and are not described as guaranteed opening odds.
