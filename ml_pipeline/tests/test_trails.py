from uuid import uuid4

import pytest
from ml_pipeline.config import GraphSettings
from ml_pipeline.neo4j_store.queries import trail_query
from neo4j import GraphDatabase


@pytest.mark.parametrize("bad", [0, 7, True, "1] MATCH (n) RETURN n"])
def test_reject_invalid_depth(bad: object) -> None:
    with pytest.raises(ValueError):
        trail_query(bad)  # type: ignore[arg-type]


@pytest.mark.integration
def test_trails_in_running_neo4j() -> None:
    config = GraphSettings()
    user, password = config.neo4j_auth.get_secret_value().split("/", 1)
    prefix = uuid4().hex
    with (
        GraphDatabase.driver(config.neo4j_uri, auth=(user, password)) as driver,
        driver.session() as session,
        session.begin_transaction() as tx,
    ):
        try:
            tx.run(
                """
            UNWIND $edges AS e
            MERGE (a:Account {account_id:$p+e[0]})
            MERGE (b:Account {account_id:$p+e[1]})
            CREATE (a)-[:TRANSFERRED {ts:e[2],txn_id:$p+e[0]+e[1]}]->(b)
            """,
                edges=[["a", "b", 5], ["b", "c", 8], ["b", "d", 4], ["b", "e", 20]],
                p=prefix,
            ).consume()
            params = {"account": prefix + "a", "t0": 0, "t1": 25, "max_gap": 4, "limit": 20}
            outgoing = {tuple(r["accounts"]) for r in tx.run(trail_query(2), params)}
            assert outgoing == {
                (prefix + "a", prefix + "b"),
                (prefix + "a", prefix + "b", prefix + "c"),
            }
            params["account"] = prefix + "c"
            incoming = {tuple(r["accounts"]) for r in tx.run(trail_query(2, "in"), params)}
            assert incoming == {
                (prefix + "b", prefix + "c"),
                (prefix + "a", prefix + "b", prefix + "c"),
            }
        finally:
            tx.rollback()
