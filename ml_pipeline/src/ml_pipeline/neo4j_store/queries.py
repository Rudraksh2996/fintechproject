"""Parameterized account trails. Transfer timestamps use UTC epoch seconds."""

from typing import Literal


def trail_query(k: int, direction: Literal["in", "out"] = "out") -> str:
    if type(k) is not int or k not in range(1, 7):
        raise ValueError("k must be an integer from 1 to 6")
    if direction not in ("in", "out"):
        raise ValueError("Unknown trail direction")
    edges = f"[:TRANSFERRED*1..{k}]"
    # Always traverse in money-flow order, even when the selected account
    # is the destination. This keeps timestamps and the returned path aligned.
    pattern = (
        f"(a:Account {{account_id:$account}})-{edges}->(:Account)"
        if direction == "out"
        else f"(:Account)-{edges}->(a:Account {{account_id:$account}})"
    )
    return f"""
    MATCH path={pattern}
    WITH path, relationships(path) AS rels
    WHERE all(r IN rels WHERE $t0 <= r.ts AND r.ts <= $t1)
      AND all(i IN range(0,size(rels)-2) WHERE rels[i].ts <= rels[i+1].ts
        AND rels[i+1].ts - rels[i].ts <= $max_gap)
    RETURN [n IN nodes(path) | n.account_id] AS accounts,
           [r IN rels | r.txn_id] AS transfers
    LIMIT $limit
    """
