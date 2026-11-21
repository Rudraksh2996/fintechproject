from collections import Counter

from ml_pipeline.evaluation.folds import SEEDS, grouped_folds
from ml_pipeline.evaluation.metrics import metrics, summary


def test_tied_predictions_and_typology_recall() -> None:
    row = metrics([1, 0, 1, 0], [0.8, 0.8, 0.2, 0.2], ["a", None, "b", None], 0.5, 2)
    assert row == {
        "pr_auc": 0.5,
        "roc_auc": 0.5,
        "precision_at_k": 0.5,
        "recall_at_1pct_fpr": 0.0,
        "recall/a": 1.0,
        "recall/b": 0.0,
    }
    assert summary([row] * 15)["pr_auc"] == {"mean": 0.5, "std": 0.0}


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
