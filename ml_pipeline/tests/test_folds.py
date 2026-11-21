from collections import Counter

from ml_pipeline.evaluation.folds import SEEDS, grouped_folds


def test_identical_reproducible_partitions_and_group_isolation() -> None:
    communities = {i: i // 10 for i in range(320)}
    rings = {i: (i // 3, str(i // 3 % 4)) for i in range(120)}
    plan = grouped_folds(communities, rings)
    assert len(plan) == 15 and plan == grouped_folds(communities, rings)
    assert len({f.test for f in plan if f.index == 0}) == 3
    for seed in SEEDS:
        rows = [f for f in plan if f.seed == seed]
        assert Counter(a for f in rows for a in f.test) == Counter(communities.keys())
        for f in rows:
            assigned = {}
            for part, ids in enumerate((f.train, f.validation, f.test)):
                assert {rings[i][1] for i in ids if i in rings} == {"0", "1", "2", "3"}
                for i in ids:
                    key = ("ring", rings[i][0]) if i in rings else ("community", communities[i])
                    assert assigned.setdefault(key, part) == part
            assert len(set(f.train) | set(f.validation) | set(f.test)) == 320
