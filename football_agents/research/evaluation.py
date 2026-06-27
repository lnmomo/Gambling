from __future__ import annotations

from typing import Callable

import numpy as np


OUTCOMES = ("home", "draw", "away")


def _arrays(probabilities: np.ndarray, outcomes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    probabilities = np.asarray(probabilities, dtype=float)
    outcomes = np.asarray(outcomes)
    if probabilities.ndim != 2 or probabilities.shape[1] != 3 or len(probabilities) != len(outcomes):
        raise ValueError("Expected an n x 3 probability matrix and n outcomes")
    if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-6):
        raise ValueError("Each probability row must sum to one")
    labels = np.column_stack([outcomes == outcome for outcome in OUTCOMES]).astype(float)
    return np.clip(probabilities, 1e-12, 1.0), labels


def evaluate_probabilities(probabilities: np.ndarray, outcomes: np.ndarray, bins: int = 10) -> dict[str, object]:
    probabilities, labels = _arrays(probabilities, outcomes)
    indices = labels.argmax(axis=1)
    brier = np.mean(np.sum((probabilities - labels) ** 2, axis=1))
    cumulative_error = np.cumsum(probabilities - labels, axis=1)[:, :-1]
    rps = np.mean(np.sum(cumulative_error**2, axis=1) / 2)
    log_loss = -np.mean(np.log(probabilities[np.arange(len(indices)), indices]))
    classwise: dict[str, float] = {}
    for column, outcome in enumerate(OUTCOMES):
        error = 0.0
        for lower in np.linspace(0, 1, bins, endpoint=False):
            upper = lower + 1 / bins
            mask = (probabilities[:, column] >= lower) & (
                (probabilities[:, column] < upper) | ((upper >= 1) & (probabilities[:, column] <= 1))
            )
            if mask.any():
                error += mask.mean() * abs(probabilities[mask, column].mean() - labels[mask, column].mean())
        classwise[outcome] = float(error)
    confidence = probabilities.max(axis=1)
    correct = probabilities.argmax(axis=1) == indices
    top_ece = 0.0
    for lower in np.linspace(0, 1, bins, endpoint=False):
        upper = lower + 1 / bins
        mask = (confidence >= lower) & ((confidence < upper) | ((upper >= 1) & (confidence <= 1)))
        if mask.any():
            top_ece += mask.mean() * abs(confidence[mask].mean() - correct[mask].mean())
    return {
        "sample_count": len(outcomes), "brier_score": float(brier), "rps": float(rps),
        "log_loss": float(log_loss), "top_label_ece": float(top_ece),
        "classwise_ece": classwise, "macro_classwise_ece": float(np.mean(list(classwise.values()))),
    }


def paired_bootstrap_difference(
    first: np.ndarray, second: np.ndarray, outcomes: np.ndarray,
    metric: Callable[[np.ndarray, np.ndarray], float], *, samples: int = 2000, seed: int = 20260622,
) -> dict[str, float]:
    first, labels = _arrays(first, outcomes)
    second, _ = _arrays(second, outcomes)
    rng = np.random.default_rng(seed)
    differences = np.empty(samples)
    for index in range(samples):
        selected = rng.integers(0, len(outcomes), len(outcomes))
        sampled_outcomes = np.asarray(outcomes)[selected]
        differences[index] = metric(first[selected], sampled_outcomes) - metric(second[selected], sampled_outcomes)
    estimate = metric(first, outcomes) - metric(second, outcomes)
    return {
        "difference": float(estimate),
        "ci95_low": float(np.quantile(differences, 0.025)),
        "ci95_high": float(np.quantile(differences, 0.975)),
        "probability_first_better": float(np.mean(differences < 0)),
    }
