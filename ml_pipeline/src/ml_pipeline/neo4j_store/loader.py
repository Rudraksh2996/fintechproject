"""Load verified generator outputs in bounded, retryable Neo4j transactions."""

import hashlib
import json
from pathlib import Path

import pandas as pd
from neo4j import Driver, ManagedTransaction


class GraphLoadError(Exception):
    """A graph input or batch failed validation."""


_QUERIES = {
    "accounts": """
        MERGE (a:Account {account_id:r.account_id})
        SET a.type=r.type, a.created_at=r.created_at, a.home_country=r.home_country
        MERGE (d:Device {device_id:r.device_id}) MERGE (a)-[:USED_DEVICE]->(d)
        MERGE (ip:IP {ip:r.ip}) MERGE (a)-[:LOGGED_FROM]->(ip)
    """,
    "transactions": """
        MATCH (a:Account {account_id:r.src}), (b:Account {account_id:r.dst})
        MERGE (a)-[t:TRANSFERRED {txn_id:r.txn_id}]->(b)
        SET t.ts=r.ts, t.amount=r.amount, t.channel=r.channel
    """,
    "labels": """
        MERGE (l:Label {account_id:r.account_id})
        SET l.ring_id=r.ring_id, l.typology=r.typology, l.label=r.label
    """,
}


def _batch(tx: ManagedTransaction, query: str, rows: list[dict[str, object]]) -> None:
    record = tx.run("UNWIND $rows AS r " + query + " RETURN count(*) AS n", rows=rows).single(
        strict=True
    )
    if record["n"] != len(rows):
        raise GraphLoadError("Unresolved transfer endpoint")


def load(driver: Driver, directory: Path, batch_size: int = 500) -> dict[str, int]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    manifest = json.loads((directory / "manifest.json").read_text())
    for name in _QUERIES:
        with (directory / f"{name}.parquet").open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["hashes"][name]:
                raise GraphLoadError(f"Dataset hash mismatch for {name}")
    counts = {}
    with driver.session() as session:
        for name, query in _QUERIES.items():
            data = pd.read_parquet(directory / f"{name}.parquet")
            for start in range(0, len(data), batch_size):
                rows = [
                    {str(k): v for k, v in row.items()}
                    for row in data.iloc[start : start + batch_size].to_dict("records")
                ]
                session.execute_write(_batch, query, rows)
            counts[name] = len(data)
    return counts
