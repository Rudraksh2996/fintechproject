"""Compute model inputs exclusively from observed accounts and transfers."""

from collections import defaultdict
from itertools import combinations
from pathlib import Path

import networkx as nx  # type: ignore[import-untyped]
import numpy as np
import pandas as pd
from ml_pipeline.features.structural import cycle_counts, pagerank


def features(directory: Path, seed: int, threshold: float) -> pd.DataFrame:
    accounts = pd.read_parquet(
        directory / "accounts.parquet",
        columns=["account_id", "device_id", "ip", "created_at", "type"],
    )
    tx = pd.read_parquet(directory / "transactions.parquet", columns=["src", "dst", "ts", "amount"])
    graph = nx.DiGraph()
    graph.add_nodes_from(accounts.account_id)
    projected = nx.Graph()
    projected.add_nodes_from(graph)
    for a, b, value in (
        tx.groupby(["src", "dst"], as_index=False)["amount"]
        .sum()
        .itertuples(index=False, name=None)
    ):
        graph.add_edge(a, b, weight=float(value))
        projected.add_edge(
            a, b, weight=projected.get_edge_data(a, b, {}).get("weight", 0) + float(value)
        )
    ranks = pagerank(graph)
    between = nx.betweenness_centrality(graph, k=min(32, len(graph)), seed=seed)
    scc = {a: len(group) for group in nx.strongly_connected_components(graph) for a in group}
    cycles = cycle_counts(graph)
    infra_weight = float(tx.amount.median()) if len(tx) else 1
    for col in ("device_id", "ip"):
        accounts[col + "_degree"] = accounts.groupby(col).account_id.transform("size") - 1
        for _, group in accounts.groupby(col):
            for a, b in combinations(group.account_id, 2):
                projected.add_edge(
                    a, b, weight=projected.get_edge_data(a, b, {}).get("weight", 0) + infra_weight
                )
    communities = {
        a: i
        for i, group in enumerate(
            nx.community.louvain_communities(projected, seed=seed, weight="weight")
        )
        for a in group
    }
    times: defaultdict[int, list[int]] = defaultdict(list)
    holds: defaultdict[int, list[int]] = defaultdict(list)
    last_in: dict[int, int] = {}
    structured: defaultdict[int, int] = defaultdict(int)
    for a, b, t, amount in tx.sort_values("ts", kind="stable").itertuples(index=False, name=None):
        for account in (a, b):
            times[account].append(t)
            structured[account] += int(0.9 * threshold <= amount < threshold)
        if a in last_in:
            holds[a].append(t - last_in[a])
        last_in[b] = t
    asof = int(tx.ts.max()) if len(tx) else int(accounts.created_at.max())
    rows = []
    for row in accounts.to_dict("records"):
        a = int(row["account_id"])
        incoming = graph.in_degree(a, weight="weight")
        outgoing = graph.out_degree(a, weight="weight")
        gaps = np.diff(times[a])
        mu, sigma = (float(gaps.mean()), float(gaps.std())) if len(gaps) else (0.0, 0.0)
        rows.append(
            {
                "account_id": a,
                "account_type": row["type"],
                "community": communities[a],
                "pagerank": ranks[a],
                "betweenness": between[a],
                "scc_size": scc[a],
                "cycles": cycles[a],
                "in_degree": graph.in_degree(a),
                "out_degree": graph.out_degree(a),
                "inflow": incoming,
                "outflow": outgoing,
                "in_out_flow_ratio": incoming / max(outgoing, 0.01),
                "median_hold": float(np.median(holds[a])) if holds[a] else 0.0,
                "p10_hold": float(np.quantile(holds[a], 0.1)) if holds[a] else 0.0,
                "burstiness": (sigma - mu) / (sigma + mu) if sigma + mu else 0.0,
                "near_threshold_share": structured[a] / max(1, len(times[a])),
                "device_degree": row["device_id_degree"],
                "ip_degree": row["ip_degree"],
                "age_days": (asof - int(row["created_at"])) / 86400,
            }
        )
    return pd.DataFrame(rows)
