"""Seeded transaction graph. Only the ground-truth table identifies ring members."""

import hashlib
import json
import random
from pathlib import Path

import pandas as pd

SCALES = {"lite": (6000, 80000, 60), "demo": (8000, 120000, 90), "full": (50000, 1000000, 90)}
TYPOLOGIES = ("dispersion", "pass_through", "cycle", "structuring", "shared_infrastructure")
START = 1704067200


def generate(
    directory: Path,
    scale: str = "lite",
    seed: int = 42,
    threshold: float = 10000,
    label_noise: float = 0,
) -> None:
    if threshold <= 0 or not 0 <= label_noise <= 1:
        raise ValueError("Invalid reporting threshold or noise probability")
    n, target, days = SCALES[scale]
    rng = random.Random(seed)
    accounts = list(range(n))
    roles = rng.choices(["retail", "business", "merchant", "payroll"], weights=[84, 10, 5, 1], k=n)
    merchants = [i for i in accounts if roles[i] == "merchant"]
    payroll = [i for i in accounts if roles[i] == "payroll"]
    shuffled = rng.sample(accounts, n)
    sizes = [3, 3, 4, 4, 5, 5, 5, 7] * 5 if scale == "lite" else [5] * (n // 250)
    rng.shuffle(sizes)
    ring_count = len(sizes)
    members = iter(shuffled[: sum(sizes)])
    ordinary = shuffled[sum(sizes) :]
    devices = [f"d{i}" for i in accounts]
    ips = [f"ip{rng.randrange(max(1, n // 2))}" for i in accounts]
    for i in accounts:
        if rng.random() < 0.08:
            devices[i] = devices[(i - 1) % n]
    labels = []
    hard_negatives: list[tuple[int, str]] = []
    edges: list[tuple[int, int, int, float, str]] = []

    def emit(a: int, b: int, ts: int, amount: float, channel: str = "transfer") -> None:
        if a == b:
            raise ValueError("Self transfer")
        edges.append((a, b, START + ts, round(amount, 2), channel))

    def daytime() -> int:
        day = rng.randrange(days - 1)
        if day % 7 in (5, 6) and rng.random() < 0.6:
            day = max(0, day - 2)
        return day * 86400 + int(max(0, min(23.99, rng.gauss(14, 4))) * 3600)

    for ring in range(ring_count):
        group = [next(members) for _ in range(sizes[ring])]
        kind = TYPOLOGIES[ring % len(TYPOLOGIES)]
        beneficiary = rng.choice(ordinary)
        for a in group:
            labels.append((a, ring, kind, int(rng.random() >= label_noise)))
            # Independent ordinary merchant payments guarantee mule camouflage.
            emit(
                a,
                rng.choice([m for m in merchants if m != a]),
                daytime(),
                rng.lognormvariate(4, 1),
                "card",
            )
            if kind == "shared_infrastructure" or rng.random() < 0.65:
                devices[a] = devices[group[0]]
                ips[a] = ips[group[0]]
        for _ in range(rng.randint(3, 7)):
            ts = daytime()
            amount = rng.uniform(1000, threshold * 1.4)
            if kind == "dispersion":
                for j, a in enumerate(group[1:]):
                    emit(a, group[0], ts + j * 60, amount / 4)
                    emit(group[0], a, ts + 1200 + j * 80, amount * rng.uniform(0.88, 0.99) / 4)
            elif kind == "shared_infrastructure":
                for a in group:
                    emit(a, beneficiary, ts + rng.randrange(3600), amount * rng.uniform(0.5, 1.5))
            elif kind == "structuring":
                for j, a in enumerate(group[1:]):
                    emit(a, group[0], ts + j * 180, threshold * rng.uniform(0.91, 0.998))
            else:
                path = group + [group[0]] if kind == "cycle" else group
                for a, b in zip(path[:-1], path[1:], strict=True):
                    emit(a, b, ts, amount)
                    ts += rng.randrange(30, 600)
                    amount *= rng.uniform(0.97, 0.999)

    # These negative groups have overlapping shapes and infrastructure with rings.
    for j in range(ring_count):
        group = ordinary[6 * j : 6 * j + 6]
        pattern = ("payroll", "merchant", "family")[j % 3]
        hard_negatives.extend((a, pattern) for a in group)
        if pattern != "family":
            roles[group[0]] = pattern
        else:
            for a in group:
                devices[a] = devices[group[0]]
                ips[a] = ips[group[0]]
        for day in range(1, days, 14):
            ts = day * 86400 + 9 * 3600
            if pattern == "family":
                for a, b in zip(group, group[1:] + group[:1], strict=True):
                    emit(a, b, ts, rng.uniform(80, 3000))
                    ts += rng.randrange(60, 1800)
            else:
                for a in group[1:]:
                    if pattern == "payroll":
                        emit(group[0], a, ts, rng.uniform(1800, 5000), "ach")
                    else:
                        emit(a, group[0], ts, rng.lognormvariate(5, 1), "card")
    while len(edges) < target:
        a = rng.randrange(n)
        ts = daytime()
        p = rng.random()
        if p < 0.42:
            b = rng.choice(merchants)
            channel = "card"
        elif p < 0.5:
            b, a = a, rng.choice(payroll)
            channel = "ach"
        else:
            b = (
                (a + rng.choice((-1, 1)) * rng.randrange(1, 25)) % n
                if p < 0.90
                else rng.randrange(n)
            )
            channel = "transfer"
        if a != b:
            emit(a, b, ts, rng.lognormvariate(7.8 if channel == "ach" else 4.4, 1.15), channel)
    edges.sort(key=lambda edge: edge[2])
    tables = {
        "accounts": pd.DataFrame(
            {
                "account_id": accounts,
                "type": roles,
                "device_id": devices,
                "ip": ips,
                "created_at": [START - rng.randrange(7, 3000) * 86400 for _ in accounts],
                "home_country": rng.choices(["US", "GB", "IN", "CA"], k=n),
            }
        ),
        "transactions": pd.DataFrame(
            edges, columns=["src", "dst", "ts", "amount", "channel"]
        ).assign(txn_id=range(len(edges))),
        "labels": pd.DataFrame(labels, columns=["account_id", "ring_id", "typology", "label"]),
        "hard_negatives": pd.DataFrame(hard_negatives, columns=["account_id", "pattern"]),
    }
    directory.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for name, frame in tables.items():
        output = directory / f"{name}.parquet"
        frame.to_parquet(output, index=False)
        with output.open("rb") as stream:
            hashes[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {
        "scale": scale,
        "seed": seed,
        "days": days,
        "threshold": threshold,
        "label_noise": label_noise,
        "accounts": n,
        "transactions": len(edges),
        "hashes": hashes,
    }
    (directory / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n")
