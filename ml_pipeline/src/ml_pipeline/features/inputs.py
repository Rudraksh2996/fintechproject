"""Explicit model input columns. Shared by training and inference."""

from pathlib import Path

import numpy as np
import pandas as pd
from numpy.typing import NDArray

NUMERIC = (
    "pagerank",
    "betweenness",
    "scc_size",
    "cycles",
    "in_degree",
    "out_degree",
    "inflow",
    "outflow",
    "in_out_flow_ratio",
    "median_hold",
    "p10_hold",
    "burstiness",
    "near_threshold_share",
    "device_degree",
    "ip_degree",
    "age_days",
)
TYPES = ("retail", "business", "merchant", "payroll")


def model_inputs(directory: Path) -> tuple[list[int], NDArray[np.float64]]:
    frame = pd.read_parquet(
        directory / "features.parquet", columns=["account_id", "account_type", *NUMERIC]
    ).sort_values("account_id")
    if frame.account_id.duplicated().any() or not frame.account_type.isin(TYPES).all():
        raise ValueError("Invalid account features")
    matrix = frame[list(NUMERIC)].to_numpy(dtype=np.float64)
    if not np.isfinite(matrix).all():
        raise ValueError("Nonfinite account feature")
    types = np.column_stack([frame.account_type.to_numpy() == kind for kind in TYPES])
    return frame.account_id.tolist(), np.column_stack([matrix, types])
