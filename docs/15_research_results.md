# Research Results and Model Freeze

## Development Evaluation

- Period: June 2023 to May 2025
- Matches: 13,339
- Market Log Loss: 0.992956
- Proposed Log Loss: 0.992927
- Difference: -0.000029
- 95% paired-bootstrap interval: [-0.001032, 0.000946]

The development result was inconclusive. It was used to diagnose optimization scale and
to freeze the final feature, hierarchy, calibration, and validation procedure. It must not
be presented as untouched confirmatory evidence.

## Frozen Final Holdout

- Period: June 2025 to May 2026
- Matches: 6,563
- Market Log Loss: 0.999345
- Proposed Log Loss: 0.998396
- Difference: -0.000949
- 95% paired-bootstrap interval: [-0.002560, 0.000625]
- Bootstrap probability proposed is better: 0.886

Secondary holdout metrics:

| Model | Log Loss | Brier | RPS | Macro classwise ECE |
|---|---:|---:|---:|---:|
| Market | 0.999345 | 0.597576 | 0.202818 | 0.011428 |
| Global Dixon-Coles | 1.020188 | 0.611794 | 0.209468 | 0.009428 |
| Hierarchical Dixon-Coles | 1.021049 | 0.612131 | 0.209633 | 0.012404 |
| Proposed | 0.998396 | 0.597308 | 0.202710 | 0.010008 |
| Closing market reference | 0.996959 | 0.595975 | 0.201996 | 0.015248 |

## Interpretation

The frozen model improved all three proper scoring rules relative to the deployable
pre-closing market baseline, but the primary Log Loss confidence interval crossed zero.
The correct conclusion is evidence of a small directional improvement, not statistically
confirmed superiority.

The football-only models remained materially weaker than the market. Rolling features
and league residuals were disabled in half or more of the final folds by the inner
validation gate. They should remain optional challenger components rather than mandatory
production inputs.

No further tuning may use the June 2025 to May 2026 outcomes. Future confirmation must use
new prospectively archived odds and results.

## Next Confirmatory Study

1. Freeze the current probability algorithm and configuration hash.
2. Archive exact-timestamp official and external odds every hour.
3. Record predictions before outcomes are known and never overwrite them.
4. Accumulate at least 5,000 settled matches or 12 calendar months.
5. Re-run the same primary endpoint and paired-bootstrap test exactly once.
