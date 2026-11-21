"""Evaluation-only grouped assignments, shared by baseline and GNN."""

import random
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass

SEEDS = (42, 43, 44)
FOLDS = 5


@dataclass(frozen=True)
class Fold:
    seed: int
    index: int
    train: tuple[int, ...]
    validation: tuple[int, ...]
    test: tuple[int, ...]


def grouped_folds(
    communities: Mapping[int, int],
    rings: Mapping[int, tuple[int, str]],
    seeds: tuple[int, ...] = SEEDS,
) -> list[Fold]:
    """Allocate entire rings within typology and legitimate communities by size."""
    if not rings or not rings.keys() <= communities.keys():
        raise ValueError("Every ring member needs a community assignment")
    strata: dict[str, dict[int, list[int]]] = {}
    legit: defaultdict[int, list[int]] = defaultdict(list)
    types: dict[int, str] = {}
    for account, community in sorted(communities.items()):
        if account in rings:
            ring, kind = rings[account]
            if types.setdefault(ring, kind) != kind:
                raise ValueError("Inconsistent typology within a ring")
            strata.setdefault(kind, {}).setdefault(ring, []).append(account)
        else:
            legit[community].append(account)
    if not strata or len(legit) < FOLDS or min(map(len, strata.values())) < FOLDS:
        raise ValueError(
            "Five folds require five legitimate communities and five rings per typology"
        )
    plan = []
    for seed in seeds:
        rng = random.Random(seed)
        buckets: list[list[int]] = [[] for _ in range(FOLDS)]
        for groups in [*strata.values(), legit]:
            assignments = list(groups.values())
            rng.shuffle(assignments)
            assignments.sort(key=len, reverse=True)
            sizes = [0] * FOLDS
            for group in assignments:
                smallest = min(sizes)
                index = rng.choice([i for i, size in enumerate(sizes) if size == smallest])
                buckets[index].extend(group)
                sizes[index] += len(group)
        for i, held in enumerate(buckets):
            val = (i + 1) % FOLDS
            train = sorted(
                a for j, bucket in enumerate(buckets) if j not in (i, val) for a in bucket
            )
            plan.append(
                Fold(seed, i, tuple(train), tuple(sorted(buckets[val])), tuple(sorted(held)))
            )
    return plan
