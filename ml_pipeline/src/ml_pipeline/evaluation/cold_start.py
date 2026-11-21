"""Chronological four-point onboarding diagnostic for one ring-disjoint fold."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import torch
from ml_pipeline.features.pipeline import features
from ml_pipeline.gnn.model import graph_inputs
from ml_pipeline.gnn.online import score_updated_graph
from ml_pipeline.gnn.train import fit


def average_precision_score(
    labels: list[int], predictions: list[float], sample_weight: list[float]
) -> float:
    thresholds = sorted(set(predictions), reverse=True)
    previous = result = 0.0
    positives = sum(w for y, w in zip(labels, sample_weight, strict=True) if y)
    for cutoff in thresholds:
        included = [
            (y, w)
            for y, p, w in zip(labels, predictions, sample_weight, strict=True)
            if p >= cutoff
        ]
        tp = sum(y * w for y, w in included)
        result += (tp - previous) / positives * tp / sum(w for _, w in included)
        previous = tp
    return result


def run(directory: Path) -> None:
    torch.set_num_threads(int(os.environ["TORCH_NUM_THREADS"]))
    report = json.loads((directory / "metrics.json").read_text())
    fold = report["fold_assignments"][0]
    manifest = json.loads((directory / "manifest.json").read_text())
    seed, threshold = manifest["seed"], manifest["threshold"]
    accounts = pd.read_parquet(directory / "accounts.parquet")
    tx = pd.read_parquet(directory / "transactions.parquet").sort_values(["ts", "txn_id"])
    labels = pd.read_parquet(directory / "labels.parquet")
    positives = set(labels.loc[labels.label == 1, "account_id"])
    held = set(fold["test"])
    steps = (1, 3, 5, 10)
    scores: dict[int, list[float]] = {k: [] for k in steps}
    degrees = pd.concat([tx.src, tx.dst[tx.src != tx.dst]]).value_counts()
    eligible = held.intersection(degrees.index[degrees >= max(steps)])
    rng = np.random.default_rng(seed)
    # Sample without regard to model scores. Undo class sampling in reported AP.
    cohort = [
        int(a)
        for group, n in ((eligible & positives, 10), (eligible - positives, 30))
        for a in rng.choice(sorted(group), min(n, len(group)), replace=False)
    ]
    y = [int(a in positives) for a in cohort]
    sample_weights = [
        len(eligible & positives) / sum(y) if v else len(eligible - positives) / (len(y) - sum(y))
        for v in y
    ]
    with TemporaryDirectory() as tmp:
        path = Path(tmp)
        accounts[~accounts.account_id.isin(held)].to_parquet(path / "accounts.parquet", index=False)
        tx[~tx.src.isin(held) & ~tx.dst.isin(held)].to_parquet(
            path / "transactions.parquet", index=False
        )
        features(path, seed, threshold).to_parquet(path / "features.parquet", index=False)
        ids, graph = graph_inputs(path)
        index = {a: i for i, a in enumerate(ids)}
        train, valid = (
            torch.tensor([index[a] for a in fold[key]]) for key in ("train", "validation")
        )
        model, center, scale, _ = fit(
            graph,
            torch.tensor([float(a in positives) for a in ids]),
            train,
            valid,
            "graphsage",
            fold["seed"] * 10 + fold["index"],
            25,
        )
        for account in cohort:
            events = tx[(tx.src == account) | (tx.dst == account)]
            for k in steps:
                cutoff = events.iloc[k - 1]
                seen = tx[
                    (tx.ts < cutoff.ts) | ((tx.ts == cutoff.ts) & (tx.txn_id <= cutoff.txn_id))
                ]
                assert int(((seen.src == account) | (seen.dst == account)).sum()) == k
                observed_ids = set(seen.src) | set(seen.dst)
                accounts[accounts.account_id.isin(observed_ids)].to_parquet(
                    path / "accounts.parquet", index=False
                )
                seen.to_parquet(path / "transactions.parquet", index=False)
                score = score_updated_graph(path, [account], model, center, scale, seed, threshold)
                scores[k].append(score[account])
            print("completed account", account, flush=True)
    result = {
        "fold_index": fold["index"],
        "seed": fold["seed"],
        "eligible": len(eligible),
        "eligible_positives": len(eligible & positives),
        "sample_positives": sum(y),
        "sample_negatives": len(y) - sum(y),
        "accounts": cohort,
        "method": (
            "One held-out fold, same accounts with at least ten transfers at each step. "
            "Inference uses only nodes and transfers observed through the kth transfer, "
            "ordered by timestamp then transaction ID. Training uses other accounts over the "
            "full synthetic period. AP weighted to eligible fold prevalence."
        ),
        "pr_auc": {
            str(k): float(average_precision_score(y, scores[k], sample_weight=sample_weights))
            for k in steps
        },
    }
    report["cold_start"] = result
    tmp_file = directory / "metrics.cold-start.tmp"
    tmp_file.write_text(json.dumps(report))
    tmp_file.replace(directory / "metrics.json")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    import sys

    run(Path(sys.argv[1]))
