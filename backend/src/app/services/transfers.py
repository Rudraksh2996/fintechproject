"""Apply transfers atomically and rescore affected accounts from observed graph data."""

import asyncio
import json
from collections import Counter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

import pandas as pd
import torch
from ml_pipeline.gnn.infer import ring_scores
from ml_pipeline.gnn.model import Detector
from ml_pipeline.gnn.online import score_updated_graph
from neo4j import AsyncDriver, AsyncManagedTransaction
from pydantic import BaseModel, Field, model_validator


class AccountInput(BaseModel):
    account_id: int = Field(ge=0)
    type: Literal["retail", "business", "merchant", "payroll"]
    created_at: int = Field(ge=0)
    home_country: str = Field(pattern="^[A-Z]{2}$")
    device_id: str = Field(min_length=1, max_length=128)
    ip: str = Field(min_length=1, max_length=128)


class TransferInput(BaseModel):
    txn_id: int = Field(ge=0)
    src: int = Field(ge=0)
    dst: int = Field(ge=0)
    ts: int = Field(ge=0)
    amount: float = Field(gt=0, allow_inf_nan=False)
    channel: str = Field(min_length=1, max_length=32)
    new_accounts: list[AccountInput] = Field(default_factory=list, max_length=2)

    @model_validator(mode="after")
    def endpoints(self) -> "TransferInput":
        ids = [a.account_id for a in self.new_accounts]
        if (
            self.src == self.dst
            or len(ids) != len(set(ids))
            or not set(ids) <= {self.src, self.dst}
        ):
            raise ValueError("Supply unique metadata only for the two distinct endpoints")
        if any(a.created_at > self.ts for a in self.new_accounts):
            raise ValueError("Account creation must precede the transfer")
        return self


class AccountScore(BaseModel):
    account_id: int
    probability: float
    crossed_threshold: bool


class RingScore(BaseModel):
    community: int
    risk: float
    mean_probability: float
    structural_factor: float
    shared_infra_factor: float
    top_k: int


class RingSnapshot(RingScore):
    members: list[int]


class TransferResult(BaseModel):
    txn_id: int
    replayed: bool
    scores: list[AccountScore]
    detected_rings: list[RingScore] = Field(default_factory=list)


class TransferConflict(ValueError):
    """A transfer ID or account already exists with different metadata."""


class RuntimeModel:
    def __init__(self, directory: Path, seed: int, threshold: float) -> None:
        config = json.loads((directory / "model_config.json").read_text())
        scaler = json.loads((directory / "feature_scaler.json").read_text())
        self.model = Detector(config["width"], config["arch"])
        self.model.load_state_dict(
            torch.load(directory / "model.pt", map_location="cpu", weights_only=True)
        )
        self.center = torch.tensor(scaler["center"])
        self.scale = torch.tensor(scaler["scale"])
        self.seed = seed
        self.reporting_threshold = threshold
        frame = pd.read_parquet(directory / "scores.parquet", columns=["probability", "community"])
        self.initial = {
            int(a): float(p) for a, p in zip(frame.index.tolist(), frame.probability, strict=True)
        }

        self.initial_groups = {int(i): int(c) for i, c in frame.community.items()}
        rings = pd.read_parquet(directory / "ring_scores.parquet")
        self.initial_risk = dict(zip(rings.community, rings.risk, strict=True))

    def updated(
        self,
        accounts: list[dict[str, object]],
        transfers: list[dict[str, object]],
        previous_groups: dict[int, int],
    ) -> tuple[dict[int, float], list[RingSnapshot], pd.DataFrame]:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            pd.DataFrame(accounts).to_parquet(directory / "accounts.parquet", index=False)
            pd.DataFrame(transfers).to_parquet(directory / "transactions.parquet", index=False)
            ids = pd.DataFrame(accounts).account_id.astype(int).tolist()
            probabilities = score_updated_graph(
                directory,
                ids,
                self.model,
                self.center,
                self.scale,
                self.seed,
                self.reporting_threshold,
            )

            frame = pd.read_parquet(directory / "features.parquet").set_index("account_id")
            frame["probability"] = frame.index.map(probabilities)
            # Match updated Louvain groups to prior IDs by largest shared membership.
            overlaps = Counter(
                (int(g), previous_groups[int(a)])
                for a, g in frame.community.items()
                if int(a) in previous_groups
            )
            matched: dict[int, int] = {}
            used: set[int] = set()
            for (current, previous), _ in sorted(
                overlaps.items(), key=lambda item: (-item[1], item[0])
            ):
                if current not in matched and previous not in used:
                    matched[current] = previous
                    used.add(previous)
            # Allocate fresh IDs below zero (bootstrap IDs are nonnegative).
            next_id = min([-1, *previous_groups.values()]) - 1
            for group in sorted(set(frame.community)):
                if group not in matched:
                    matched[group] = next_id
                    next_id -= 1
            frame["community"] = frame.community.map(matched)
            members = frame.groupby("community").groups
            snapshots = [
                RingSnapshot(**row, members=list(map(int, members[row["community"]])))
                for row in ring_scores(frame).to_dict("records")
            ]
            return probabilities, snapshots, frame


async def apply_transfer(
    driver: AsyncDriver, model: RuntimeModel, item: TransferInput, alert_threshold: float
) -> TransferResult:
    async def write(tx: AsyncManagedTransaction) -> TransferResult:
        await (
            await tx.run(
                "MERGE (s:ScoringState {name:'ledger'}) SET s.sequence=coalesce(s.sequence,0)+1"
            )
        ).consume()
        existing = await (
            await tx.run(
                "MATCH (a)-[t:TRANSFERRED {txn_id:$id}]->(b) "
                "RETURN a.account_id AS src,b.account_id AS dst,t.ts AS ts,t.amount AS amount,"
                "t.channel AS channel,t.score_result AS stored,t.ring_result AS rings",
                id=item.txn_id,
            )
        ).single()
        if existing is not None:
            if any(
                existing[k] != getattr(item, k) for k in ("src", "dst", "ts", "amount", "channel")
            ):
                raise TransferConflict("Transfer ID already identifies another transfer")
            return TransferResult(
                txn_id=item.txn_id,
                replayed=True,
                detected_rings=[
                    RingScore.model_validate(r) for r in json.loads(existing["rings"] or "[]")
                ],
                scores=[
                    AccountScore.model_validate(s) for s in json.loads(existing["stored"] or "[]")
                ],
            )
        for account in item.new_accounts:
            row = await (
                await tx.run("MATCH (a:Account {account_id:$id}) RETURN a", id=account.account_id)
            ).single()
            if row is not None:
                raise TransferConflict("New account ID already exists")
            await (
                await tx.run(
                    """
                CREATE (a:Account {account_id:$account_id,type:$type,created_at:$created_at,
                                  home_country:$home_country})
                MERGE (d:Device {device_id:$device_id}) MERGE (a)-[:USED_DEVICE]->(d)
                MERGE (i:IP {ip:$ip}) MERGE (a)-[:LOGGED_FROM]->(i)
                """,
                    account.model_dump(),
                )
            ).consume()
        row = await (
            await tx.run(
                """
            MATCH (a:Account {account_id:$src}),(b:Account {account_id:$dst})
            CREATE (a)-[t:TRANSFERRED {txn_id:$txn_id,amount:$amount,ts:$ts,channel:$channel}]->(b)
            RETURN t.txn_id AS id
            """,
                item.model_dump(exclude={"new_accounts"}),
            )
        ).single()
        if row is None:
            raise KeyError("Unknown transfer endpoint; supply new account metadata")
        accounts = await (
            await tx.run("""
            MATCH (a:Account)-[:USED_DEVICE]->(d:Device),(a)-[:LOGGED_FROM]->(i:IP)
            RETURN a.account_id AS account_id, a.type AS type,a.created_at AS created_at,
                   min(d.device_id) AS device_id,min(i.ip) AS ip ORDER BY account_id
            """)
        ).data()
        transfers = await (
            await tx.run("""
            MATCH (a:Account)-[t:TRANSFERRED]->(b:Account) RETURN a.account_id AS src,
            b.account_id AS dst,t.ts AS ts,t.amount AS amount ORDER BY t.txn_id
            """)
        ).data()
        affected = await (
            await tx.run(
                """
            MATCH (a:Account) WHERE a.account_id IN $ids
            MATCH (a)-[:TRANSFERRED*0..2]-(b:Account)
            RETURN DISTINCT b.account_id AS id,b.probability AS old ORDER BY id
            """,
                ids=[item.src, item.dst],
            )
        ).data()
        previous = await (
            await tx.run(
                "MATCH (r:CandidateRing) RETURN r.community AS id, "
                "r.members AS members, r.risk AS risk"
            )
        ).data()
        groups = (
            {a: r["id"] for r in previous for a in r["members"]}
            if previous
            else model.initial_groups
        )
        prior_risk = {r["id"]: r["risk"] for r in previous} if previous else model.initial_risk
        scores, snapshots, frame = await asyncio.to_thread(
            model.updated, accounts, transfers, groups
        )
        detected = [
            RingScore.model_validate(r.model_dump())
            for r in snapshots
            if prior_risk.get(r.community, 0) < 100 * alert_threshold <= r.risk
        ]
        await (
            await tx.run(
                "MATCH (r:CandidateRing) WHERE NOT r.community IN $ids DELETE r",
                ids=[r.community for r in snapshots],
            )
        ).consume()
        await (
            await tx.run(
                "UNWIND $rows AS row MERGE (r:CandidateRing {community:row.community}) "
                "SET r += row",
                rows=[r.model_dump() for r in snapshots],
            )
        ).consume()
        results = [
            AccountScore(
                account_id=r["id"],
                probability=scores[r["id"]],
                crossed_threshold=(
                    r["old"] if r["old"] is not None else model.initial.get(r["id"], 0)
                )
                < alert_threshold
                <= scores[r["id"]],
            )
            for r in affected
        ]
        payload = [s.model_dump() for s in results]
        await (
            await tx.run(
                "UNWIND $rows AS r MATCH (a:Account {account_id:r.account_id}) "
                "SET a.probability=r.probability, a.scored_features=r.features",
                rows=[{**r, "features": frame.loc[r["account_id"]].to_json()} for r in payload],
            )
        ).consume()
        await (
            await tx.run(
                "MATCH ()-[t:TRANSFERRED {txn_id:$id}]->() SET t.score_result=$scores, "
                "t.ring_result=$rings",
                id=item.txn_id,
                scores=json.dumps(payload),
                rings=json.dumps([r.model_dump() for r in detected]),
            )
        ).consume()
        return TransferResult(
            txn_id=item.txn_id, replayed=False, scores=results, detected_rings=detected
        )

    async with driver.session() as session:
        return await session.execute_write(write)
