"""Tie-aware binary ranking metrics and repeated grouped-CV summaries."""

from collections.abc import Mapping, Sequence
from itertools import groupby
from math import isfinite
from statistics import mean, stdev


def metrics(
    target: list[int],
    scores: list[float],
    typologies: list[str | None],
    threshold: float,
    k: int = 100,
) -> dict[str, float]:
    """Use average precision for PR-AUC and trapezoidal ROC-AUC.

    recall@1%FPR is the highest empirical recall at an admissible threshold.
    Typology recall uses the decision threshold supplied from validation.
    """
    rows = sorted(zip(scores, target, typologies, strict=True), key=lambda r: -r[0])
    if not rows or any(y not in (0, 1) or not isfinite(p) for p, y, _ in rows):
        raise ValueError("Invalid binary predictions")
    positives = sum(target)
    negatives = len(rows) - positives
    if not positives or not negatives or k <= 0:
        raise ValueError("Both classes and a positive k are required")
    tp = fp = 0
    ap = auc = recall = 0.0
    for _, items in groupby(rows, key=lambda r: r[0]):
        group = list(items)
        hits = sum(r[1] for r in group)
        misses = len(group) - hits
        prev = tp
        tp += hits
        fp += misses
        ap += hits / positives * (tp / (tp + fp))
        auc += (tp + prev) / (2 * positives) * misses / negatives
        if fp / negatives <= 0.01:
            recall = tp / positives
    result = {
        "pr_auc": ap,
        "roc_auc": auc,
        "recall_at_1pct_fpr": recall,
        "precision_at_k": sum(r[1] for r in rows[:k]) / min(k, len(rows)),
    }
    for kind in sorted({kind for _, y, kind in rows if y and kind is not None}):
        detected = [p >= threshold for p, y, t in rows if y and t == kind]
        result[f"recall/{kind}"] = mean(detected)
    return result


def summary(folds: Sequence[Mapping[str, float]]) -> dict[str, dict[str, float]]:
    if len(folds) != 15 or any(f.keys() != folds[0].keys() for f in folds):
        raise ValueError("Expected 15 complete fold results including every typology")
    return {
        name: {"mean": mean(f[name] for f in folds), "std": stdev(f[name] for f in folds)}
        for name in folds[0]
    }
