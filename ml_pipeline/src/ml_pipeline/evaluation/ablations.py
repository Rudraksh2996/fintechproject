"""Retrain diagnostic folds in temporary storage; update only the metrics artifact."""

import hashlib
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import torch
from ml_pipeline.evaluation.metrics import metrics, summary
from ml_pipeline.features.inputs import NUMERIC
from ml_pipeline.features.pipeline import features
from ml_pipeline.gnn.model import graph_inputs
from ml_pipeline.gnn.online import score_updated_graph
from ml_pipeline.gnn.train import fit


def run(directory: Path, mode: str) -> None:
    if mode not in {"shortcut", "inductive"}:
        raise ValueError(mode)
    torch.set_num_threads(int(os.environ["TORCH_NUM_THREADS"]))
    manifest = json.loads((directory / "manifest.json").read_text())
    seed, threshold = manifest["seed"], manifest["threshold"]
    report = json.loads((directory / "metrics.json").read_text())
    labels = pd.read_parquet(directory / "labels.parquet")
    positive = set(labels.loc[labels.label == 1, "account_id"])
    kinds = dict(zip(labels.account_id, labels.typology, strict=True))
    accounts = pd.read_parquet(directory / "accounts.parquet")
    transfers = pd.read_parquet(directory / "transactions.parquet")
    results = []
    epochs = []
    weights = hashlib.sha256((directory / "model.pt").read_bytes()).hexdigest()
    with TemporaryDirectory() as tmp:
        path = Path(tmp)
        original = {int(a): int(a) for a in accounts.account_id}
        if mode == "shortcut":
            rng = np.random.default_rng(14031)
            ids = accounts.account_id.to_numpy(copy=True)
            shuffled = rng.permutation(ids)
            original = dict(zip(map(int, shuffled), map(int, ids), strict=True))
            rename = dict(zip(ids, shuffled, strict=True))
            accounts = accounts.assign(
                account_id=shuffled, created_at=rng.permutation(accounts.created_at)
            )
            accounts.iloc[rng.permutation(len(accounts))].to_parquet(
                path / "accounts.parquet", index=False
            )
            transfers.assign(
                src=transfers.src.map(rename), dst=transfers.dst.map(rename)
            ).to_parquet(path / "transactions.parquet", index=False)
            features(path, seed, threshold).to_parquet(path / "features.parquet", index=False)
        for fold in report["fold_assignments"]:
            held = fold["test"]
            if mode == "inductive":
                accounts[~accounts.account_id.isin(held)].to_parquet(
                    path / "accounts.parquet", index=False
                )
                transfers[~transfers.src.isin(held) & ~transfers.dst.isin(held)].to_parquet(
                    path / "transactions.parquet", index=False
                )
                features(path, seed, threshold).to_parquet(path / "features.parquet", index=False)
            node_ids, graph = graph_inputs(path)
            mapped = [original[a] for a in node_ids]
            index = {a: i for i, a in enumerate(mapped)}
            if mode == "shortcut":
                omit = NUMERIC.index("age_days")
                graph.x = torch.cat([graph.x[:, :omit], graph.x[:, omit + 1 :]], dim=1)
            else:
                assert set(held).isdisjoint(mapped)
            train, valid = (
                torch.tensor([index[a] for a in fold[key]]) for key in ("train", "validation")
            )
            y = torch.tensor([float(a in positive) for a in mapped])
            model, c, s, epoch = fit(
                graph, y, train, valid, "graphsage", fold["seed"] * 10 + fold["index"], 25
            )
            if mode == "inductive":
                accounts.to_parquet(path / "accounts.parquet", index=False)
                transfers.to_parquet(path / "transactions.parquet", index=False)
                updated = score_updated_graph(path, held, model, c, s, seed, threshold)
                probs = [updated[a] for a in held]
            else:
                with torch.no_grad():
                    x = ((graph.x - c) / s).clamp(-12, 12)
                    probs = (
                        model(x, graph.edge_index, graph.edge_attr)[[index[a] for a in held]]
                        .sigmoid()
                        .tolist()
                    )
            result = metrics(
                [int(a in positive) for a in held], probs, [kinds.get(a) for a in held], 0.5
            )
            print(mode, fold["seed"], fold["index"], result["pr_auc"], flush=True)
            results.append(result)
            epochs.append(epoch)
    aggregate = summary(results)
    assert weights == hashlib.sha256((directory / "model.pt").read_bytes()).hexdigest()
    report.setdefault("ablations", {})[mode] = {
        "summary": aggregate,
        "folds": results,
        "epochs": epochs,
        "shipped_model_sha256": weights,
        "fold_reference": "fold_assignments",
        "architecture": "graphsage",
    }
    temp = directory / "metrics.ablations.tmp"
    temp.write_text(json.dumps(report))
    temp.replace(directory / "metrics.json")
    print(mode, json.dumps(aggregate), flush=True)
    if (
        mode == "shortcut"
        and report["gnn"]["summary"]["pr_auc"]["mean"] - aggregate["pr_auc"]["mean"] > 0.10
    ):
        raise ValueError("Shortcut ablation exceeded the 0.10 drop limit")


if __name__ == "__main__":
    run(Path(sys.argv[1]), sys.argv[2])
