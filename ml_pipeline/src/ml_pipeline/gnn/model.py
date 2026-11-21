"""CPU graph model and label-free graph construction shared with inference."""

from pathlib import Path

import numpy as np
import pandas as pd
import torch
from ml_pipeline.features.inputs import model_inputs
from torch import Tensor, nn
from torch_geometric.data import Data  # type: ignore[import-untyped]
from torch_geometric.nn import GATv2Conv, SAGEConv  # type: ignore[import-untyped]


def graph_inputs(directory: Path) -> tuple[list[int], Data]:
    accounts, values = model_inputs(directory)
    ids = {a: i for i, a in enumerate(accounts)}
    tx = pd.read_parquet(directory / "transactions.parquet", columns=["src", "dst", "ts", "amount"])
    tx = tx.sort_values("ts", kind="stable")
    edge = torch.tensor(np.array([tx.src.map(ids), tx.dst.map(ids)]), dtype=torch.long)
    hour = 2 * np.pi * (tx.ts.to_numpy() % 86400) / 86400
    last: dict[int, int] = {}
    gaps = []
    for a, b, t in tx[["src", "dst", "ts"]].itertuples(index=False, name=None):
        gaps.append(np.log1p(t - last.get(a, t)))
        last[b] = t
    attr = np.column_stack([np.log1p(tx.amount), np.sin(hour), np.cos(hour), gaps])
    x = torch.tensor(np.sign(values) * np.log1p(np.abs(values)), dtype=torch.float32)
    return accounts, Data(x=x, edge_index=edge, edge_attr=torch.tensor(attr, dtype=torch.float32))


class Detector(nn.Module):
    def __init__(self, width: int, arch: str) -> None:
        super().__init__()
        self.arch = arch
        if arch == "graphsage":
            self.first = SAGEConv(width, 32)
            self.second = SAGEConv(32, 16)
        elif arch == "gatv2":
            self.first = GATv2Conv(width, 32, edge_dim=4)
            self.second = GATv2Conv(32, 16, edge_dim=4)
        else:
            raise ValueError("Unknown graph architecture")
        self.head = nn.Sequential(nn.Linear(width + 32 + 16, 32), nn.ReLU(), nn.Linear(32, 1))

    def forward(self, x: Tensor, edges: Tensor, attrs: Tensor) -> Tensor:
        args = (attrs,) if self.arch == "gatv2" else ()
        h = self.first(x, edges, *args).relu()
        z = self.second(h, edges, *args).relu()
        logits: Tensor = self.head(torch.cat([x, h, z], dim=1))
        return logits.flatten()
