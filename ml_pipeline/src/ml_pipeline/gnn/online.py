"""Score affected accounts on the observed graph after transfers are applied."""

from pathlib import Path

import torch
from ml_pipeline.features.pipeline import features
from ml_pipeline.gnn.model import Detector, graph_inputs
from torch import Tensor


@torch.inference_mode()
def score_updated_graph(
    directory: Path,
    affected: list[int],
    model: Detector,
    center: Tensor,
    scale: Tensor,
    seed: int,
    threshold: float,
) -> dict[int, float]:
    # Centrality, communities and cycles can change beyond the immediate endpoints.
    # Recompute from the current observed graph for exact scores on the lite preset.
    features(directory, seed, threshold).to_parquet(directory / "features.parquet", index=False)
    accounts, data = graph_inputs(directory)
    index = {a: i for i, a in enumerate(accounts)}
    x = ((data.x - center) / scale).clamp(-12, 12)
    p = model.eval()(x, data.edge_index, data.edge_attr).sigmoid()
    return {a: float(p[index[a]]) for a in affected}
