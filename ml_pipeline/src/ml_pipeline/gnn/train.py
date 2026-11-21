"""One-shot bootstrap training on shared group-disjoint CV assignments."""

import json
import os
import sys
from pathlib import Path
from statistics import median
from time import monotonic

import pandas as pd
import torch
from ml_pipeline.evaluation.baseline import evaluate
from ml_pipeline.evaluation.metrics import metrics, summary
from ml_pipeline.gnn.model import Detector, graph_inputs
from torch import Tensor
from torch_geometric.data import Data  # type: ignore[import-untyped]
from torch_geometric.loader import NeighborLoader  # type: ignore[import-untyped]


def fit(
    graph: Data, targets: Tensor, train: Tensor, valid: Tensor, arch: str, seed: int, epochs: int
) -> tuple[Detector, Tensor, Tensor, int]:
    torch.manual_seed(seed)
    center = graph.x[train].mean(0)
    scale = graph.x[train].std(0, unbiased=False).clamp(min=1e-6)
    data = Data(
        x=((graph.x - center) / scale).clamp(-12, 12),
        edge_index=graph.edge_index,
        edge_attr=graph.edge_attr,
    )
    loader = NeighborLoader(
        data, num_neighbors=[12, 8], input_nodes=train, batch_size=512, shuffle=True
    )
    model = Detector(data.x.size(1), arch)
    optim = torch.optim.AdamW(model.parameters(), lr=0.004)
    y = targets[train]
    criterion = torch.nn.BCEWithLogitsLoss(pos_weight=(len(y) - y.sum()) / y.sum())
    best = -1.0
    selected = 0
    state = {}
    for epoch in range(1, epochs + 1):
        model.train()
        for batch in loader:
            size = batch.batch_size
            optim.zero_grad()
            loss = criterion(
                model(batch.x, batch.edge_index, batch.edge_attr)[:size], targets[batch.n_id[:size]]
            )
            loss.backward()
            optim.step()
        if len(valid):
            model.eval()
            with torch.no_grad():
                scores = model(data.x, data.edge_index, data.edge_attr)[valid].sigmoid().tolist()
            ap = metrics(targets[valid].int().tolist(), scores, [None] * len(scores), 0.5)["pr_auc"]
            if ap > best:
                best = ap
                state = {k: v.detach().clone() for k, v in model.state_dict().items()}
                selected = epoch
            if epoch - selected >= 4:
                break
    if state:
        model.load_state_dict(state)
    return model.eval(), center, scale, selected or epochs


def train(directory: Path) -> None:
    started = monotonic()
    torch.set_num_threads(int(os.environ["TORCH_NUM_THREADS"]))
    arch = os.environ.get("GNN_ARCH", "graphsage")
    evaluate(directory)
    folds = json.loads((directory / "cv_folds.json").read_text())
    accounts, graph = graph_inputs(directory)
    index = {a: i for i, a in enumerate(accounts)}
    labels = pd.read_parquet(directory / "labels.parquet")
    positive = set(labels.loc[labels.label == 1, "account_id"])
    kinds = dict(zip(labels.account_id, labels.typology, strict=True))
    targets = torch.tensor([float(a in positive) for a in accounts])
    reports = []
    selected = []
    for fold in folds:
        tr, va, te = (
            torch.tensor([index[a] for a in fold[part]]) for part in ("train", "validation", "test")
        )
        model, c, s, epoch = fit(
            graph, targets, tr, va, arch, fold["seed"] * 10 + fold["index"], 25
        )
        with torch.no_grad():
            pred = (
                model(((graph.x - c) / s).clamp(-12, 12), graph.edge_index, graph.edge_attr)[te]
                .sigmoid()
                .tolist()
            )
        report = metrics(
            targets[te].int().tolist(), pred, [kinds.get(a) for a in fold["test"]], 0.5
        )
        reports.append(report)
        selected.append(epoch)
        print(
            f"seed={fold['seed']} fold={fold['index']} "
            f"PR-AUC={report['pr_auc']:.4f} epochs={epoch}",
            flush=True,
        )
    result = {
        "baseline": json.loads((directory / "baseline_cv.json").read_text()),
        "gnn": {"folds": reports, "summary": summary(reports)},
        "seeds": sorted({f["seed"] for f in folds}),
        "fold_count": 5,
        "fold_assignments": folds,
        "validation_selected_epochs": selected,
        "arch": arch,
    }
    (directory / "metrics.json").write_text(json.dumps(result))
    avg = summary(reports)["pr_auc"]["mean"]
    if not 0.75 <= avg <= 0.98:
        raise ValueError(f"Gate 3 mean PR-AUC outside accepted range: {avg}")
    epochs = int(median(selected))
    model, c, s, _ = fit(
        graph,
        targets,
        torch.arange(len(accounts)),
        torch.tensor([], dtype=torch.long),
        arch,
        int(os.environ.get("SEED", "42")),
        epochs,
    )
    torch.save(model.state_dict(), directory / "model.pt")
    (directory / "model_config.json").write_text(
        json.dumps({"arch": arch, "width": graph.x.size(1), "epochs": epochs})
    )
    (directory / "feature_scaler.json").write_text(
        json.dumps({"center": c.tolist(), "scale": s.tolist()})
    )
    elapsed = monotonic() - started
    result["training_seconds"] = elapsed
    (directory / "metrics.json").write_text(json.dumps(result))
    print(f"mean CV PR-AUC={avg:.4f}; CV and final fit took {elapsed:.2f}s", flush=True)
    if elapsed >= 300:
        raise ValueError("Bootstrap training exceeded 300 seconds")


if __name__ == "__main__":
    train(Path(sys.argv[1]))
