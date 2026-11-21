import json
from pathlib import Path

import pandas as pd
from ml_pipeline.generator.dataset import TYPOLOGIES, generate


def test_lite_determinism_and_camouflage(tmp_path: Path) -> None:
    first, second = tmp_path / "first", tmp_path / "second"
    for out in (first, second):
        generate(out)
    for file in first.iterdir():
        assert file.read_bytes() == (second / file.name).read_bytes()
    manifest = json.loads((first / "manifest.json").read_text())
    assert (manifest["accounts"], manifest["transactions"], manifest["days"]) == (3000, 40000, 60)
    labels = pd.read_parquet(first / "labels.parquet")
    transfers = pd.read_parquet(first / "transactions.parquet")
    neg = pd.read_parquet(first / "hard_negatives.parquet")
    assert set(labels.typology) == set(TYPOLOGIES)
    assert set(neg.pattern) == {"payroll", "merchant", "family"}
    assert set(neg.account_id).isdisjoint(labels.account_id)
    assert set(labels.account_id) <= set(transfers.loc[transfers.channel == "card", "src"])
    assert 0.01 <= len(labels) / 3000 <= 0.03
    # Inspect the actual negative transfers within each dedicated group.
    for _, group in neg.groupby(neg.index // 6):
        ids = group.account_id.to_list()
        edges = transfers[transfers.src.isin(ids) & transfers.dst.isin(ids)]
        pairs = set(zip(edges.src, edges.dst, strict=True))
        if group.pattern.iloc[0] == "payroll":
            assert {(ids[0], a) for a in ids[1:]} <= pairs
        elif group.pattern.iloc[0] == "merchant":
            assert {(a, ids[0]) for a in ids[1:]} <= pairs
        else:
            assert set(zip(ids, ids[1:] + ids[:1], strict=True)) <= pairs
