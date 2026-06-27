from __future__ import annotations

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


OUTCOMES = ("home", "draw", "away")


class ProbabilityBaselines:
    def __init__(self, seed: int = 20260622) -> None:
        self.models = {
            "multinomial_logit": make_pipeline(
                StandardScaler(), LogisticRegression(C=0.2, max_iter=1000, random_state=seed),
            ),
            "random_forest": RandomForestClassifier(
                n_estimators=120, max_depth=8, min_samples_leaf=20, max_features="sqrt",
                n_jobs=-1, random_state=seed,
            ),
            "hist_gradient_boosting": HistGradientBoostingClassifier(
                max_iter=150, learning_rate=0.05, max_leaf_nodes=15, min_samples_leaf=30,
                l2_regularization=2.0, random_state=seed,
            ),
        }

    def fit(self, features: np.ndarray, outcomes: np.ndarray) -> "ProbabilityBaselines":
        for model in self.models.values():
            model.fit(features, outcomes)
        return self

    def predict(self, features: np.ndarray) -> dict[str, np.ndarray]:
        output: dict[str, np.ndarray] = {}
        for name, model in self.models.items():
            raw = model.predict_proba(features)
            classes = list(model.classes_)
            output[name] = np.column_stack([raw[:, classes.index(outcome)] for outcome in OUTCOMES])
        return output
