"""Exercise the shipped model under restricted observable inputs, then evaluate rings."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import torch
from ml_pipeline.gnn.infer import score
from neo4j import GraphDatabase


def verify(directory: Path) -> None:
    torch.set_num_threads(int(os.environ["TORCH_NUM_THREADS"]))
    read = pd.read_parquet

    def guarded(path: Path, *, columns: list[str]) -> pd.DataFrame:
        if (
            path.name not in {"features.parquet", "transactions.parquet"}
            or not columns
            or (set(columns) & {"label", "ring_id", "typology", "ground_truth"})
        ):
            raise AssertionError("Inference attempted to read ground truth")
        return read(path, columns=columns)

    with (
        patch.object(pd, "read_parquet", guarded),
        patch.object(
            GraphDatabase,
            "driver",
            side_effect=AssertionError("Inference attempted a graph-store read"),
        ),
    ):
        score(directory)
    scores = read(directory / "scores.parquet")
    risks = read(directory / "ring_scores.parquet")
    assert len(scores) == len(read(directory / "accounts.parquet"))
    assert scores.probability.between(0, 1).all() and risks.risk.between(0, 100).all()
    assert np.allclose(
        risks.risk,
        100
        * (
            0.6 * risks.mean_probability
            + 0.2 * risks.structural_factor
            + 0.2 * risks.shared_infra_factor
        ),
    )
    labels = read(directory / "labels.parquet").set_index("account_id")
    top = risks.nlargest(10, "risk")
    hits = 0
    for community in top.community:
        # A true candidate contains at least half of a planted ring, with >=2
        # distinct members. Report the definition alongside the precision.
        members = scores.index[scores.community == community]
        contained = labels[labels.index.isin(members)].ring_id.value_counts()
        hits += int(
            any(n >= 2 and n * 2 >= (labels.ring_id == r).sum() for r, n in contained.items())
        )
    report = json.loads((directory / "metrics.json").read_text())
    report["ring_precision_at_10"] = {
        "value": hits / len(top),
        "hits": hits,
        "candidates": len(top),
        "definition": "contains >=2 members and >=50% of one planted ring",
    }
    (directory / "metrics.json").write_text(json.dumps(report))
    for model in ("baseline", "gnn"):
        print(model, json.dumps(report[model]["summary"], sort_keys=True))
    print("ring_precision_at_10", report["ring_precision_at_10"])
    print("inference label isolation passed")


if __name__ == "__main__":
    verify(Path(sys.argv[1]))
