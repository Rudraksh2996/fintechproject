from collections import Counter
from pathlib import Path

import networkx as nx
import pandas as pd
import pytest
from ml_pipeline.features.inputs import model_inputs
from ml_pipeline.features.pipeline import features
from ml_pipeline.features.structural import cycle_counts
from neo4j import GraphDatabase


def test_simple_cycles_match_exhaustive_reference() -> None:
    graph = nx.gnp_random_graph(12, 0.3, seed=17, directed=True)
    expected = Counter(a for cycle in nx.simple_cycles(graph, length_bound=6) for a in cycle)
    assert cycle_counts(graph) == expected


def test_feature_and_model_inputs_cannot_read_ground_truth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    accounts = pd.DataFrame(
        {
            "account_id": [1, 2, 3],
            "device_id": ["a", "a", "c"],
            "ip": ["x", "y", "z"],
            "created_at": [0, 0, 0],
            "type": ["retail", "retail", "business"],
            "label": [1, 0, 0],
        }
    )
    accounts.to_parquet(tmp_path / "accounts.parquet")
    pd.DataFrame(
        {
            "src": [1, 2, 3],
            "dst": [2, 3, 1],
            "ts": [1, 2, 3],
            "amount": [10, 20, 30],
            "ring_id": [1, 1, 1],
        }
    ).to_parquet(tmp_path / "transactions.parquet")
    read = pd.read_parquet

    def guarded(path: Path, *, columns: list[str]) -> pd.DataFrame:
        assert path.name in {"accounts.parquet", "transactions.parquet", "features.parquet"}
        assert set(columns).isdisjoint({"label", "ring_id", "typology", "community_label"})
        return read(path, columns=columns)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("Feature and inference inputs must not connect to the label store")

    monkeypatch.setattr(pd, "read_parquet", guarded)
    monkeypatch.setattr(GraphDatabase, "driver", forbidden)
    frame = features(tmp_path, 42, 10000)
    assert set(frame.cycles) == {1}
    frame.assign(label=1, ring_id=1).to_parquet(tmp_path / "features.parquet")
    ids, x = model_inputs(tmp_path)
    assert ids == [1, 2, 3] and x.shape == (3, 20)
