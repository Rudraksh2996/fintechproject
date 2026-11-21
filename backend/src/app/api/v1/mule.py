"""Bounded forensic queries on observed transfers, enriched with bootstrap scores."""

from pathlib import Path
from typing import Annotated, Literal

import pandas as pd
from fastapi import APIRouter, HTTPException, Query
from ml_pipeline.neo4j_store.queries import trail_query
from neo4j import AsyncDriver
from pydantic import BaseModel, JsonValue


class Ring(BaseModel):
    community: int
    risk: float
    mean_probability: float
    structural_factor: float
    shared_infra_factor: float
    top_k: int


class Node(BaseModel):
    account_id: int
    type: str
    probability: float
    volume: float


class Link(BaseModel):
    txn_id: int
    src: int
    dst: int
    ts: int
    amount: float
    channel: str


class Graph(BaseModel):
    nodes: list[Node]
    links: list[Link]
    truncated: bool


class Trail(BaseModel):
    accounts: list[int]
    transfers: list[int]


class AccountDetail(BaseModel):
    account: Node
    community: int | None
    features: dict[str, JsonValue]
    devices: list[str]
    ips: list[str]


class Period(BaseModel):
    ts: int
    transfers: int
    amount: float


class Truth(BaseModel):
    account_id: int
    ring_id: int
    typology: str


def routes(driver: AsyncDriver, directory: Path, demo: bool) -> APIRouter:
    router = APIRouter(prefix="/api/v1/mule")

    def members(ring_id: int) -> list[int]:
        frame = pd.read_parquet(directory / "scores.parquet", columns=["community"])
        ids = list(map(int, frame.index[frame.community == ring_id].tolist()))
        if not ids:
            raise HTTPException(404, "Unknown candidate ring")
        return ids

    def truth(ids: list[int]) -> list[Truth]:
        labels = pd.read_parquet(directory / "labels.parquet")
        return [
            Truth.model_validate(row)
            for row in labels[labels.account_id.isin(ids)].to_dict("records")
        ]

    @router.get("/rings")
    def rings(
        min_risk: Annotated[float, Query(ge=0, le=100)] = 0,
        typology: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[Ring]:
        df = pd.read_parquet(directory / "ring_scores.parquet")
        result = [Ring.model_validate(row) for row in df[df.risk >= min_risk].to_dict("records")]
        if typology:
            if not demo:
                raise HTTPException(422, "Typology filter requires labeled synthetic data")
            result = [
                r
                for r in result
                if any(t.typology == typology for t in truth(members(r.community)))
            ]
        return result[:limit]

    async def network(ids: list[int] | None, t0: int, t1: int, n: int) -> Graph:
        if t0 > t1:
            raise HTTPException(422, "Invalid time window")
        async with driver.session() as session:
            data = await (
                await session.run(
                    """
                MATCH (a:Account)-[t:TRANSFERRED]->(b:Account)
                WHERE $t0<=t.ts AND t.ts<=$t1 AND ($ids IS NULL OR
                  (a.account_id IN $ids AND b.account_id IN $ids))
                RETURN a.account_id AS src,b.account_id AS dst,t.txn_id AS txn_id,t.ts AS ts,
                  t.amount AS amount,t.channel AS channel,a.type AS atype,b.type AS btype,
                  a.probability AS ap,b.probability AS bp ORDER BY t.ts DESC,t.txn_id LIMIT $cap
                """,
                    ids=ids,
                    t0=t0,
                    t1=t1,
                    cap=n * 6 + 1,
                )
            ).data()
        probs = pd.read_parquet(
            directory / "scores.parquet", columns=["probability"]
        ).probability.to_dict()
        nodes: dict[int, Node] = {}
        links = []
        truncated = len(data) > n * 6
        for r in data[: n * 6]:
            if len(nodes.keys() | {r["src"], r["dst"]}) > n:
                truncated = True
                continue
            links.append(Link.model_validate(r))
            for key, typ, p in (("src", "atype", "ap"), ("dst", "btype", "bp")):
                a = r[key]
                nodes.setdefault(
                    a,
                    Node(
                        account_id=a,
                        type=r[typ],
                        probability=r[p] if r[p] is not None else probs.get(a, 0),
                        volume=0,
                    ),
                ).volume += r["amount"]
        return Graph(nodes=list(nodes.values()), links=links, truncated=truncated)

    @router.get("/graph/overview")
    async def overview(
        t0: int = 0, t1: int = 2**62, max_nodes: Annotated[int, Query(ge=2, le=3000)] = 500
    ) -> Graph:
        return await network(None, t0, t1, max_nodes)

    @router.get("/rings/{ring_id}/graph")
    async def ring_graph(ring_id: int, t0: int = 0, t1: int = 2**62) -> Graph:
        return await network(members(ring_id), t0, t1, 3000)

    @router.get("/ground-truth/{ring_id}")
    def ground_truth(ring_id: int) -> list[Truth]:
        if not demo:
            raise HTTPException(404, "Unavailable in live mode")
        return truth(members(ring_id))

    @router.get("/accounts/{account_id}")
    async def account(account_id: int) -> AccountDetail:
        async with driver.session() as session:
            row = await (
                await session.run(
                    """
                MATCH (a:Account {account_id:$id})
                RETURN a.type AS type,a.probability AS score,
                  [(a)-[:USED_DEVICE]->(d:Device)|d.device_id] AS devices,
                  [(a)-[:LOGGED_FROM]->(i:IP)|i.ip] AS ips,
                  reduce(total=0.0, amt IN [(a)-[r:TRANSFERRED]-()|r.amount]|total+amt) AS volume
                """,
                    id=account_id,
                )
            ).single()
        if row is None:
            raise HTTPException(404, "Unknown account")
        df = pd.read_parquet(
            directory / "features.parquet", filters=[("account_id", "==", account_id)]
        )
        attrs = df.to_dict("records")[0] if len(df) else {}
        score = row["score"]
        if score is None:
            probs = pd.read_parquet(directory / "scores.parquet", columns=["probability"])
            score = float(probs.probability.to_dict()[account_id])
        return AccountDetail(
            account=Node(
                account_id=account_id, type=row["type"], probability=score, volume=row["volume"]
            ),
            community=attrs.get("community"),
            features={str(k): v for k, v in attrs.items()},
            devices=row["devices"],
            ips=row["ips"],
        )

    @router.get("/accounts/{account_id}/trail")
    async def trail(
        account_id: int,
        k: Annotated[int, Query(ge=1, le=6)] = 2,
        direction: Literal["in", "out"] = "out",
        t0: int = 0,
        t1: int = 2**62,
        max_gap: Annotated[int, Query(ge=0)] = 3600,
    ) -> list[Trail]:
        if t0 > t1:
            raise HTTPException(422, "Invalid time window")
        async with driver.session() as session:
            found = await (
                await session.run(
                    "MATCH (a:Account {account_id:$id}) RETURN a.account_id", id=account_id
                )
            ).single()
            if found is None:
                raise HTTPException(404, "Unknown account")
            data = await (
                await session.run(
                    trail_query(k, direction),
                    account=account_id,
                    t0=t0,
                    t1=t1,
                    max_gap=max_gap,
                    limit=200,
                )
            ).data()
        return [Trail.model_validate(row) for row in data]

    @router.get("/timeline")
    async def timeline(ring_id: int) -> list[Period]:
        async with driver.session() as session:
            rows = await (
                await session.run(
                    """
              MATCH (a:Account)-[r:TRANSFERRED]->(b:Account)
              WHERE a.account_id IN $ids AND b.account_id IN $ids
              RETURN toInteger(r.ts/3600)*3600 AS ts,count(r) AS transfers,sum(r.amount) AS amount
              ORDER BY ts""",
                    ids=members(ring_id),
                )
            ).data()
        return [Period.model_validate(r) for r in rows]

    return router
