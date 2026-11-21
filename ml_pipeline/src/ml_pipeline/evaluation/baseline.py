"""Feature-only, class-weighted logistic regression on the shared CV partitions."""

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from ml_pipeline.evaluation.folds import SEEDS, grouped_folds
from ml_pipeline.evaluation.metrics import metrics, summary
from ml_pipeline.features.inputs import model_inputs
from numpy.typing import NDArray


def logistic(
    x: NDArray[np.float64], y: NDArray[np.float64], test: NDArray[np.float64]
) -> NDArray[np.float64]:
    center = x.mean(axis=0)
    scale = x.std(axis=0).clip(min=1e-8)
    train = np.column_stack([np.ones(len(x)), ((x - center) / scale).clip(-12, 12)])
    held = np.column_stack([np.ones(len(test)), ((test - center) / scale).clip(-12, 12)])
    # L2 regularized weighted Newton updates; intercept is unpenalized.
    weights = np.where(y == 1, 0.5 / y.mean(), 0.5 / (1 - y.mean())) / len(y)
    beta = np.zeros(train.shape[1])
    penalty = np.eye(len(beta)) * 0.01
    penalty[0, 0] = 0
    for _ in range(40):
        p = 1 / (1 + np.exp(-(train @ beta).clip(-40, 40)))
        grad = train.T @ (weights * (p - y)) + penalty @ beta
        hessian = (train.T * (weights * p * (1 - p))) @ train + penalty
        step = np.linalg.solve(hessian, grad)
        beta -= step
        if np.abs(step).max() < 1e-7:
            break
    return 1 / (1 + np.exp(-(held @ beta).clip(-40, 40)))


def evaluate(directory: Path) -> None:
    accounts, x = model_inputs(directory)
    index = {a: i for i, a in enumerate(accounts)}
    features = pd.read_parquet(directory / "features.parquet", columns=["account_id", "community"])
    labels = pd.read_parquet(directory / "labels.parquet")
    rings = {
        int(a): (int(r), str(t))
        for a, r, t in labels[["account_id", "ring_id", "typology"]].itertuples(
            index=False, name=None
        )
    }
    positives = set(labels.loc[labels.label == 1, "account_id"])
    y = np.array([a in positives for a in accounts], dtype=float)
    plan = grouped_folds(dict(zip(features.account_id, features.community, strict=True)), rings)
    reports = []
    for fold in plan:
        train = [index[a] for a in fold.train]
        test = [index[a] for a in fold.test]
        scores = logistic(x[train], y[train], x[test])
        reports.append(
            metrics(
                y[test].astype(int).tolist(),
                scores.tolist(),
                [rings[a][1] if a in rings else None for a in fold.test],
                0.5,
            )
        )
    (directory / "cv_folds.json").write_text(json.dumps([asdict(f) for f in plan]))
    result = {
        "model": "weighted_logistic",
        "seeds": SEEDS,
        "folds": reports,
        "summary": summary(reports),
        "decision_threshold": 0.5,
        "std": "sample across 15 fold scores",
    }
    (directory / "baseline_cv.json").write_text(json.dumps(result, indent=2))
