"""Load fitted artifacts for label-free account and community scoring."""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from ml_pipeline.gnn.model import Detector, graph_inputs


@torch.inference_mode()
def score(directory: Path) -> None:
    config = json.loads((directory / "model_config.json").read_text())
    scaler = json.loads((directory / "feature_scaler.json").read_text())
    ids, data = graph_inputs(directory)
    model = Detector(config["width"], config["arch"])
    model.load_state_dict(torch.load(directory / "model.pt", map_location="cpu", weights_only=True))
    x = ((data.x - torch.tensor(scaler["center"])) / torch.tensor(scaler["scale"])).clamp(-12, 12)
    prob = model.eval()(x, data.edge_index, data.edge_attr).sigmoid().numpy()
    features = (
        pd.read_parquet(
            directory / "features.parquet",
            columns=[
                "account_id",
                "community",
                "cycles",
                "in_out_flow_ratio",
                "device_degree",
                "ip_degree",
            ],
        )
        .set_index("account_id")
        .loc[ids]
    )
    features["probability"] = prob
    features[["community", "probability"]].to_parquet(directory / "scores.parquet")
    groups = []
    for community, rows in features.groupby("community"):
        top = rows.nlargest(5, "probability")
        member = float(top.probability.mean())
        ratio = top.in_out_flow_ratio.to_numpy()
        balance = np.minimum(ratio, 1 / np.maximum(ratio, 1e-8))
        structure = float(np.mean((balance + np.minimum(1, np.log1p(top.cycles) / np.log(11))) / 2))
        infra = float(np.mean(np.minimum(1, (top.device_degree + top.ip_degree) / 10)))
        groups.append(
            {
                "community": community,
                "top_k": len(top),
                "mean_probability": member,
                "structural_factor": structure,
                "shared_infra_factor": infra,
                "risk": 100 * (0.6 * member + 0.2 * structure + 0.2 * infra),
            }
        )
    pd.DataFrame(groups).sort_values("risk", ascending=False).to_parquet(
        directory / "ring_scores.parquet", index=False
    )
