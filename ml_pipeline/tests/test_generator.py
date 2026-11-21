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
    assert (manifest["accounts"], manifest["transactions"], manifest["days"]) == (6000, 80000, 60)
    labels = pd.read_parquet(first / "labels.parquet")
    transfers = pd.read_parquet(first / "transactions.parquet")
    neg = pd.read_parquet(first / "hard_negatives.parquet")
    assert set(labels.typology) == set(TYPOLOGIES)
    assert set(neg.pattern) == {"payroll", "merchant", "family"}
    assert set(neg.account_id).isdisjoint(labels.account_id)
    assert set(labels.account_id) <= set(transfers.loc[transfers.channel == "card", "src"])
    assert len(labels) == labels.account_id.nunique() == 180
    assert labels.groupby("typology").ring_id.nunique().to_dict() == dict.fromkeys(TYPOLOGIES, 8)
    sizes = labels.groupby("ring_id").size()
    assert len(sizes) == 40 and sizes.min() == 3 and sizes.max() == 7 and sizes.mean() == 4.5
    accounts = pd.read_parquet(first / "accounts.parquet").set_index("account_id")
    for _, group in labels.groupby("ring_id"):
        ids = group.account_id.tolist()
        kind = group.typology.iloc[0]
        sent = transfers[transfers.src.isin(ids)]
        edges = sent[sent.dst.isin(ids)]
        pairs = set(zip(edges.src, edges.dst, strict=True))
        hops = set(zip(ids[:-1], ids[1:], strict=True))
        if kind == "cycle":
            assert hops | {(ids[-1], ids[0])} <= pairs
        elif kind == "pass_through":
            assert hops <= pairs
        elif kind == "dispersion":
            assert all((v, ids[0]) in pairs and (ids[0], v) in pairs for v in ids[1:])
        elif kind == "structuring":
            near = edges[(edges.amount >= 9000) & (edges.amount < 10000) & (edges.dst == ids[0])]
            assert set(ids[1:]) <= set(near.src)
        else:
            assert (
                accounts.loc[ids, "device_id"].nunique() == accounts.loc[ids, "ip"].nunique() == 1
            )
            assert sent.groupby("dst").src.nunique().max() >= len(ids)
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
