# Build progress

## Phase 4 gateway checkpoint — Gate 4 pending

The gateway loads the shipped model at startup. Transfer submission scores the updated
graph using the inductive evaluation path, persists affected scores, and publishes
upward account threshold crossings. The read routes use Postgres, Neo4j and bootstrap
artifacts. Live checks against the seeded databases returned HTTP 200 for a ring graph,
demo ground truth, timeline, bounded overview, account detail and transfer trail.

Gateway integration tests used the seeded Postgres database, bootstrap artifacts,
and a disposable Neo4j instance for writes. The two tests exercised health, alert
drilldown, radar, metrics, a WebSocket crossing, idempotent replay, and a conflicting
duplicate transaction ID. Recorded test output:

```text
2 passed, 42 warnings in 2.94s
```

Resume with config CRUD and activation, detection/ingestion jobs, Postgres LISTEN and
alert WebSocket delivery, ring events, and the replay scheduler through real ingestion.
Finish the Streamlit workbench (display inductive evaluation and cold-start limits),
gateway/workbench Compose services, OpenAPI type generation, and the full Gate 4
integration, coverage and AppTest checks. Run `bash infra/scripts/gate4.sh` once
implemented and record its output here before advancing.

## 2026-11-22 — Gate 3 PASSED on macOS / OrbStack linux/arm64

Ran `bash infra/scripts/gate3.sh` against Neo4j and the four-thread one-shot
CPU bootstrap. Exit 0. Full output: `infra/verification/phase3/gate3-macos.log`.
Saved `metrics-lite.json` alongside it with all 15 fold assignments, both
estimators' fold results, chosen epochs, thresholds and measured duration.
The artifacts volume contains model.pt, model_config.json, feature_scaler.json,
metrics.json, scores.parquet and ring_scores.parquet.

```text
10 passed in 2.15s
All checks passed!
Success: no issues found in 34 source files
{"accounts": 6000, "transactions": 80000, "labels": 180}
{"accounts": 6000, "communities": 61}
mean CV PR-AUC=0.9504; CV and final fit took 50.61s
ring_precision_at_10 {'value': 1.0, 'hits': 10, 'candidates': 10, 'definition': 'contains >=2 members and >=50% of one planted ring'}
inference label isolation passed
Gate 3 PASSED
```

Sample mean ± SD over the same five grouped folds at each of three seeds:

| Metric | GraphSAGE | Feature-only logistic regression |
|---|---:|---:|
| PR-AUC | .950 ± .047 | .692 ± .118 |
| ROC-AUC | .998 ± .002 | .985 ± .006 |
| Recall at 1% FPR | .939 ± .082 | .554 ± .208 |
| Cycle recall | .969 ± .083 | 1.000 ± .000 |
| Dispersion recall | .910 ± .178 | .838 ± .134 |
| Pass-through recall | .882 ± .120 | .840 ± .096 |
| Shared infrastructure recall | .905 ± .133 | .837 ± .189 |
| Structuring recall | 1.000 ± .000 | .981 ± .050 |

Pre-Phase-4 sensitivity checks, same 15 held-out folds, mean ± sample SD:

| Evaluation | PR-AUC | Recall at 1% FPR |
|---|---:|---:|
| Shipped GraphSAGE protocol | .9504 ± .0465 | .9389 ± .0822 |
| No age; remapped IDs and shuffled creation order | .9571 ± .0365 | .9546 ± .0543 |
| Inductive, held-out accounts added back | .9096 ± .1035 | .8712 ± .1925 |

Ran `python -m ml_pipeline.evaluation.ablations /artifacts shortcut` and
`python -m ml_pipeline.evaluation.ablations /artifacts inductive` in the
existing bootstrap image with updated source mounted read-only. Shortcut PR-AUC
increased by .0067; no generator remediation was indicated. The inductive run
removed all test accounts and their incident edges before recomputing features
and fitting. It restored their observed transfer history and scored through the
same function used by the transfer API. Average PR-AUC decreased by .0408 and
recall by .0677, with substantially larger fold variation. These measurements
do not establish first-transfer-only accuracy. Model weights were SHA-256 checked
before and after both diagnostics. Full fold results are in the artifact volume's
`metrics.json` and the tracked `infra/verification/phase3/metrics-lite.json`.

Phase 6 disk plan: use the slim E2E build with `playwright install --with-deps chromium`
and headless SwiftShader. Check free space before/after builds, prune dangling
images after each build, and stop below 5 GiB.

This is synthetic transductive evaluation: observable graph topology and
unsupervised graph features are available across partitions. Model parameters,
scaling and early stopping use training/validation accounts. Final refit runs
once per bootstrap invocation on all accounts with the median selected epoch
count. The GNN mean fell between the 0.75 and 0.98 gates. Ring precision is a
full-demo coverage diagnostic; it does not measure candidate purity.
Neo4j cgroup peak 1,057,607,680 bytes / limit 1,342,177,280; no OOM or restart.
PyG used the native arm64 torch-sparse sampler; PyG warns this fallback is deprecated.

Next phase: Phase 4 gateway and Streamlit. Use the verified artifacts and
databases, implement the Section 5 contracts, replay and workbench, then run Gate 4.

## 2026-11-22 — revised lite evaluation, Gate 3 still open

Migration 0002 records fetched historical price intervals atomically with bars.
The vendor/cache tests span MLK Day and check fresh provider instances. Ran
`uv run alembic upgrade head` then `uv run pytest -q infra/tests edgar_pipeline/tests/test_prices.py`:
7 passed in 2.13s.

The approved lite preset supersedes the older numbers below. At seed 42 it has
6,000 accounts, 80,000 transfers and 180 positive accounts in 40 disjoint rings.
Each of the five typologies has eight rings. Sizes range from three to seven
(mean 4.5). The deterministic generation test compares every output byte.

```text
uv run mule generate --output ../work/lite-v2
uv run mule load --output ../work/lite-v2
{"accounts": 6000, "transactions": 80000, "labels": 180}
uv run mule load --output ../work/lite-v2
{"accounts": 6000, "transactions": 80000, "labels": 180}
Neo4j counts after replay: 6000 accounts, 80000 transfers, 180 labels, 0 label edges
cgroup memory.peak: 1055997952 bytes; memory.max: 1342177280 bytes
docker inspect: OOMKilled=false restarts=0
uv run mule features --output ../work/lite-v2
{"accounts": 6000, "communities": 61}
uv run mule baseline --output ../work/lite-v2
uv run pytest -q ml_pipeline -> 10 passed in 1.61s
uv run mypy --strict -> Success: no issues found in 31 source files
```

The fold generator groups positives by ring and legitimate accounts by Louvain
community. Seeds 42/43/44 each use five test folds. Each rotation holds one
other fold for validation and fits preprocessing on training accounts only.
All 15 baseline fold records and their sample standard deviations are in
`infra/verification/phase3/baseline-lite.json`. Baseline PR-AUC (average
precision) 0.692 ± 0.118; ROC-AUC 0.985 ± 0.006; recall@1%FPR 0.554 ± 0.208.
Per-typology recall at threshold 0.5: cycle 1.000 ± 0.000, dispersion 0.838 ± 0.134,
pass-through 0.840 ± 0.096, shared infrastructure 0.837 ± 0.189,
structuring 0.981 ± 0.050. These are baseline diagnostics only.

Training image storage is the immediate resource constraint. The Linux arm64
CPython 3.12 Torch 2.8.0 CPU wheel measured 101905972 bytes compressed and
410939507 bytes of uncompressed files (wheel directory). At the last disk
check the Mac had 482 MiB free, below even the combined wheel and unpacked
files, before PyG, build layers and artifacts. Free several GiB on the Mac.
Keep the approved lite scale unless measured runtime or Neo4j memory requires
the approved 5,000/65,000 fallback.

Resume with `df -h .` and `export PATH="$HOME/.orbstack/bin:/usr/local/bin:$PATH" UV_NO_EDITABLE=1`.
Use the saved lite-v2 CV assignments (or regenerate with the baseline command).
Implement bootstrap-only GNN CV on identical folds with training-only transforms,
the inference-path isolation test, risk score and top-10 precision. Time the
four-thread bootstrap. Record both estimators' fold/seed config and all metrics
in metrics.json. Apply the 0.75 minimum and 0.98 difficulty threshold to mean
GNN PR-AUC, preserve both runs if difficulty changes, then fit the shipping
model once on all data. Run the full Gate 3 before advancing.

### Phase 3 generator checkpoint

Added `mule generate --output DIRECTORY` for lite/demo/full, using SEED and
REPORTING_THRESHOLD. Lite generates 3,000 accounts, 40,000 transfers over 60 days,
and 12 rings (2% mule prevalence). Verified byte-identical Parquet and manifests
across two fresh runs. Every mule makes ordinary card purchases. Negative payroll,
merchant and family groups are disjoint from mule members; tests inspect their
actual fan-out, fan-in and cycles. Ground truth is exported separately.

```text
UV_NO_EDITABLE=1 uv run pytest -q ml_pipeline/tests/test_generator.py -> 1 passed in 5.00s
uv run mypy --strict -> Success: no issues found in 23 source files
```

Gate 3 remains open. Next implement the batched graph loader and features using
only account, transfer and infrastructure inputs; test the reachable feature and
inference paths against forbidden label columns and Label-node reads. Train the
feature-only baseline and GNN on identical persisted ring-disjoint splits and
report per-typology recall for both. Time lite training inside the four-thread
bootstrap container (limit 300 seconds). If test PR-AUC exceeds 0.98, retain
that result, increase difficulty, rerun, and record both. The Mac had about
0.5 GiB free during generator verification; check disk before the training build.

### Phase 2 live prices

LivePrices implements the backtest PriceProvider and requests US daily closes
from Stooq, falling back to yfinance on transport or data failure. Results are
cached in price_bars with source provenance. The integration tests mock the
Stooq transport and yfinance history boundary, use real Postgres, and verify a
second provider instance reads cached prices without a vendor call. Ranges
containing an exchange holiday can trigger another fetch because the cache
checks weekday coverage. Replay scheduling belongs to Phase 4.

Gate command: `bash infra/scripts/gate2.sh`.

```text
 Container fintech-platform-postgres-1 Waiting
 Container fintech-platform-postgres-1 Healthy
...100000 window entries, 100 merged alerts, 0.233 seconds
............
15 passed in 7.71s
All checks passed!
Success: no issues found in 21 source files
{"run_id": 17, "seen": 853, "inserted": 0, "quarantined": 1}
{"alerts": ["ZXQ00", "ZXQ01", "ZXQ02", "ZXQ03", "ZXQ04", "ZXQ05", "ZXQ06", "ZXQ07", "ZXQ08", "ZXQ09", "ZXQ40", "ZXQ42"]}
{"run_id": 18, "seen": 853, "inserted": 0, "quarantined": 1}
{"alerts": ["ZXQ00", "ZXQ01", "ZXQ02", "ZXQ03", "ZXQ04", "ZXQ05", "ZXQ06", "ZXQ07", "ZXQ08", "ZXQ09", "ZXQ40", "ZXQ42"]}
Verified 12 planted alerts, 31 trap issuers, 3 amendments and 450 benchmark closes.
Optional live EDGAR: skipped, offline (no configured SEC contact)
Gate 2 PASSED
```

### Phase 2 benchmark and threshold audit

Counted entries inside the rolling loop and verified the 1,000 unique member IDs
for each of 100 issuers. The focused run took 0.196 seconds. Appended immutable
fixture accessions for a three-insider $100,000 day-14 trigger, a day-15 miss,
and a $99,000 cluster that first triggers at $100,000 on the 4/A filing date.
The PostgreSQL test checks both sides of the amendment before rolling back.
Gate command: `bash infra/scripts/gate2.sh`.

```text
Uninstalled 1 package in 0.83ms
Installed 1 package in 3ms
...100000 window entries, 100 merged alerts, 0.228 seconds
..........
13 passed in 7.66s
All checks passed!
Success: no issues found in 20 source files
{"run_id": 12, "seen": 853, "inserted": 10, "quarantined": 1}
{"alerts": ["ZXQ00", "ZXQ01", "ZXQ02", "ZXQ03", "ZXQ04", "ZXQ05", "ZXQ06", "ZXQ07", "ZXQ08", "ZXQ09", "ZXQ40", "ZXQ42"]}
{"run_id": 13, "seen": 853, "inserted": 0, "quarantined": 1}
{"alerts": ["ZXQ00", "ZXQ01", "ZXQ02", "ZXQ03", "ZXQ04", "ZXQ05", "ZXQ06", "ZXQ07", "ZXQ08", "ZXQ09", "ZXQ40", "ZXQ42"]}
Verified 12 planted alerts, 31 trap issuers, 3 amendments and 450 benchmark closes.
Optional live EDGAR: skipped, offline (no configured SEC contact)
Gate 2 PASSED
```

Client date: **2026-11-21 (Asia/Calcutta)**.

## Current status — Gate 2 passed; Phase 3 in progress

Implemented the incoming and outgoing temporal trail query with whitelisted
depth (1–6), parameterized values, a time window and a maximum inter-hop gap.
A live Neo4j test proved both directions, rejecting a backward timestamp and
an excessive gap, then rolled back the test graph. Additional tests reject
out-of-bounds, boolean and injection inputs.

```text
UV_NO_EDITABLE=1 uv run pytest -q ml_pipeline -> 5 passed in 7.06s
uv run mypy --strict -> Success: no issues found in 20 source files
```

Resume Phase 3 with the seeded lite/demo/full Parquet generator and manifest.
Then build the batched Neo4j loader, remaining graph queries, NetworkX features,
leakage-safe ring splits, baseline, CPU training and inference. Run the complete
Gate 3 and record measured PR-AUC, precision and training time before Phase 4.

## Phase 2 live gate

Ran `bash infra/scripts/gate2.sh` against the local Compose PostgreSQL service.
The initial seed inserted 254 transactions from 843 filings with one quarantine.
Repeated seeds inserted zero additional transactions. Joint filings preserve all
owners in raw XML; each XML purchase is attributed once to the first listed owner.
The SEC contact in .env is the example identity, so no live request was made.
Live-price retrieval and chronological replay still require integration before
the final application gate. Exact gate output (exit 0):

```text
   Building edgar-pipeline @ file:///Users/ishan_mac/Documents/Codex/2026-11-21/remotio/fintech-platform/edgar_pipeline
      Built edgar-pipeline @ file:///Users/ishan_mac/Documents/Codex/2026-11-21/remotio/fintech-platform/edgar_pipeline
Prepared 1 package in 193ms
Uninstalled 3 packages in 1ms
Installed 3 packages in 3ms
 ~ edgar-pipeline==0.1.0 (from file:///Users/ishan_mac/Documents/Codex/2026-11-21/remotio/fintech-platform/edgar_pipeline)
 ~ fintech-gateway==0.1.0 (from file:///Users/ishan_mac/Documents/Codex/2026-11-21/remotio/fintech-platform/backend)
 ~ ml-pipeline==0.1.0 (from file:///Users/ishan_mac/Documents/Codex/2026-11-21/remotio/fintech-platform/ml_pipeline)
 Container fintech-platform-postgres-1 Running
 Container fintech-platform-postgres-1 Waiting
 Container fintech-platform-postgres-1 Healthy
..100000 transactions, 100 merged alerts, 0.188 seconds
..........
12 passed in 5.72s
All checks passed!
Success: no issues found in 19 source files
{"run_id": 7, "seen": 843, "inserted": 0, "quarantined": 1}
{"alerts": ["ZXQ00", "ZXQ01", "ZXQ02", "ZXQ03", "ZXQ04", "ZXQ05", "ZXQ06", "ZXQ07", "ZXQ08", "ZXQ09"]}
{"run_id": 8, "seen": 843, "inserted": 0, "quarantined": 1}
{"alerts": ["ZXQ00", "ZXQ01", "ZXQ02", "ZXQ03", "ZXQ04", "ZXQ05", "ZXQ06", "ZXQ07", "ZXQ08", "ZXQ09"]}
Verified 10 planted alerts, 30 trap issuers, 2 amendments and 450 benchmark closes.
Optional live EDGAR: skipped, offline (no configured SEC contact)
Gate 2 PASSED
```

Next: implement the Section 4 synthetic graph generator, loader, temporal
queries, features, leakage tests, baseline and CPU-only bootstrap training.
Run Gate 3 before starting Phase 4.

## Historical Phase 1 verification on macOS arm64

Both Compose services reached healthy. Docker 29.8.2, Compose v5.5.0 and uv Python
3.13.14. The first attempts in this session passed the live database checks but
pytest could not import the editable package: Python skipped the macOS-hidden
editable .pth files. Installed the same revision as ordinary wheels with
`uv sync --all-packages --frozen --no-editable`. Exact successful invocation:
`UV_NO_EDITABLE=1 COMPOSE_PROGRESS=quiet bash infra/scripts/gate1.sh` (exit 0).

```text
Docker Compose version v5.5.0
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running downgrade 0001 -> , Initial insider schema, database invariants, role grants, and notifications.
INFO  [alembic.runtime.migration] Context impl PostgresqlImpl.
INFO  [alembic.runtime.migration] Will assume transactional DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 0001, Initial insider schema, database invariants, role grants, and notifications.
id, name, type, entityType, labelsOrTypes, properties, ownedIndex, propertyType
4, "account_id_unique", "UNIQUENESS", "NODE", ["Account"], ["account_id"], "account_id_unique", NULL
6, "device_id_unique", "UNIQUENESS", "NODE", ["Device"], ["device_id"], "device_id_unique", NULL
8, "ip_unique", "UNIQUENESS", "NODE", ["IP"], ["ip"], "ip_unique", NULL
10, "label_account_unique", "UNIQUENESS", "NODE", ["Label"], ["account_id"], "label_account_unique", NULL
12, "transfer_id_unique", "RELATIONSHIP_UNIQUENESS", "RELATIONSHIP", ["TRANSFERRED"], ["txn_id"], "transfer_id_unique", NULL
         conname         
-------------------------
 uq_form4_accession_line
(1 row)

      indexname       
----------------------
 ix_form4_ticker_date
(1 row)

Checking PostgreSQL and Neo4j definitions and workbench_ro INSERT permissions
{"postgres": "passed", "unique_constraint": true, "ticker_date_index": true, "readonly_insert_denied": true}
{"neo4j": "passed", "constraints": [["account_id_unique", "UNIQUENESS", ["Account"], ["account_id"]], ["device_id_unique", "UNIQUENESS", ["Device"], ["device_id"]], ["ip_unique", "UNIQUENESS", ["IP"], ["ip"]], ["label_account_unique", "UNIQUENESS", ["Label"], ["account_id"]], ["transfer_id_unique", "RELATIONSHIP_UNIQUENESS", ["TRANSFERRED"], ["txn_id"]]], "time_index": true}
All checks passed!
Success: no issues found in 10 source files
.....                                                                    [100%]
5 passed in 0.13s

> fintech-command-center@0.1.0 lint
> eslint src --max-warnings 0


> fintech-command-center@0.1.0 typecheck
> tsc --noEmit

Gate 1 PASSED
```

## Phase 2 — in progress

Implemented the typed lxml parser and focused tests for joint owners, XML namespaces,
4/A identification, filtering transaction codes and dispositions, stable XML line
numbers, footnote-only prices, and typed parse errors. Local checks:

```text
uv run ruff check . -> All checks passed!
uv run mypy --strict -> Success: no issues found in 11 source files
UV_NO_EDITABLE=1 uv run --frozen pytest -q -> 9 passed in 0.77s
```

On this host refresh the local package wheel after parser changes with
`uv sync --frozen --all-packages --no-editable --reinstall-package edgar-pipeline`.
The SEC client and filing discovery are implemented in commits ef9e02f and 3068a6c.
The mock-transport client tests measured 21 requests across two concurrent clients,
enforcing at least one second between each request and the tenth following request.
Tests also exercised Retry-After, shared 403 cooldown, identity checks and cache hits.
Discovery tests resolved a daily index, quarterly index and archived submissions
through ticker lookup to the same raw primary XML. No live SEC check was run.

```text
UV_NO_EDITABLE=1 uv run pytest -q edgar_pipeline/tests/test_http_client.py -> 3 passed in 4.22s
UV_NO_EDITABLE=1 uv run pytest -q edgar_pipeline/tests/test_discovery.py -> 1 passed in 0.68s
uv run ruff check . -> All checks passed!
uv run mypy --strict -> Success: no issues found in 13 source files
```

Next implement transactional Postgres ingestion with quarantine, multi-owner attribution, amendment
supersession and idempotency tests. Then implement the detector, conviction score,
price providers, backtester, fixtures and CLI. Run the complete Gate 2 specified in
Section 8 (including the 100k-row benchmark and planted-cluster/trap assertions)
before starting Phase 3. Gate 2 has not run.

## Historical macOS attempts

Retry: restarted OrbStack and confirmed Docker 29.8.2 on aarch64. With 1.0 GiB
free at the start, `COMPOSE_PROGRESS=plain bash infra/scripts/gate1.sh` exited 1
while extracting Neo4j's `libjvm.so`: `no space left on device`. The host then
reported 179 MiB free. Full output: `infra/verification/phase1/macos-retry.log`.
Free several GiB on the Mac data volume and rerun the commands below.

Gate 1 exited 1 during Docker image extraction. OrbStack has 7.816 GiB and
Compose v5.5.0. The arm64 smoke test passed. Installed uv Python 3.13.14,
pinned 3.13, synced all workspace packages and installed frontend dependencies.
Applied Section 10 resource and schema-verification changes. Local checks:

```text
uv run --frozen ruff check .   -> All checks passed!
uv run --frozen mypy --strict  -> Success: no issues found in 10 source files
uv run --frozen pytest -q      -> 5 passed in 1.09s
```

After copying .env.example to .env, ran `bash infra/scripts/gate1.sh`.
The full command output is in `infra/verification/phase1/macos-attempt.log`.
Docker returned `no space left on device` before either database became healthy.
The Mac reported 122 MiB free after failure. The integration checks remain pending.
Free space on the Mac data volume, then in the repository run:

```sh
export PATH="$HOME/.orbstack/bin:/usr/local/bin:$PATH"
df -h .
bash infra/scripts/gate1.sh
```

Record a passing run, commit and push before starting Phase 2.

## Original Windows checkpoint

**Phase 1 implemented; Gate 1 BLOCKED. Phases 2–6 NOT STARTED.**

The required `docker compose up -d postgres neo4j` failed because `docker` is not
installed/available on PATH. Neither the Docker CLI nor Desktop exists in the standard
Windows installation location. No PostgreSQL or Neo4j service was launched. Local checks
below are additional evidence, not a replacement for the required integration gate.

## Phase 1 — Infrastructure and schemas

Built:

- Requested top-level monorepo directories and tracked empty directories for later phases.
- Installable EDGAR, mule, and gateway packages, plus the workbench workspace package.
- Pinned Python dependencies with `uv.lock`; pinned Node dev tools with `package-lock.json`.
- SQLAlchemy 2.0 models and an independent frozen Alembic initial revision for all ten
  domain tables, required uniqueness constraints and indexes, typed monetary columns,
  amendment references, raw XML, provenance, quarantine, and score breakdown JSONB.
- `cluster_alerts` INSERT notification trigger, company update timestamp trigger,
  validated detection weights/caps, an initial default config, and database enforcement
  of exactly one active config using a partial unique index plus deferred trigger.
- Postgres admin/app/read-only separation; environment-driven role passwords, SELECT-only
  grants for `workbench_ro`, and a test that attempts INSERT after disabling its session
  read-only default so that ACL enforcement is tested directly.
- Neo4j uniqueness constraints for Account, Device, IP, Label, and TRANSFERRED IDs, a
  transfer timestamp index, and an explicit wait for indexes to become online.
- Compose database services with persistence, bounded memory, health checks, and loopback
  ports; a non-root schema-runner Dockerfile with frozen dependency installation.
- Ruff, strict mypy, strict TypeScript, ESLint with explicit `any` prohibited, environment
  validation, Make targets, a real database verification script, and a fail-fast gate script.
- Five offline tests for table/constraint contracts, frozen migration/ORM agreement,
  SEC rate and identity validation, safe credential URL construction, and Compose contracts.

### Setup commands actually run

From the parent workspace:

```powershell
python -m venv work/.venv
work/.venv/Scripts/python.exe -m pip install uv==0.9.11
```

From this repository:

```powershell
../../work/.venv/Scripts/uv.exe sync --all-packages
```

Result: 45 packages resolved; 44 packages installed, including editable workspace packages.
`npm.cmd install --no-audit --no-fund` in `frontend/` installed 120 Node packages and generated
the lockfile. npm reported that pinned ESLint 9.39.1 is no longer supported; lint itself
passes. This is recorded as a tooling maintenance limitation, not suppressed.

### Required Gate 1

| Command/check | Actual result |
| --- | --- |
| `docker compose up -d postgres neo4j` | **FAILED**, PowerShell exit 1: `The term 'docker' is not recognized` |
| `C:/Program Files/Git/bin/bash.exe infra/scripts/gate1.sh` | **BLOCKED**, exit 127: `Gate 1 BLOCKED: Docker is required; no database checks were run.` |
| Online `alembic upgrade head`, `downgrade base`, `upgrade head` | **NOT RUN**: no database services available |
| `psql` unique/index checks and actual read-only INSERT denial | **NOT RUN**: no database services available |
| `cypher-shell 'SHOW CONSTRAINTS'` and online graph index checks | **NOT RUN**: no database services available |
| Ruff and strict mypy | **PASS** on implemented Phase 1 source, details below |

**Gate 1 has not passed. No gate was weakened and no integration output was fabricated.**

### Final local verification

Commands were run from this repository using its installed interpreter. Raw outputs and
command results are saved under `infra/verification/phase1/`.

| Exact command | Exit | Output summary |
| --- | --- | --- |
| `.venv/Scripts/python.exe -m ruff check .` | 0 | `All checks passed!` |
| `.venv/Scripts/python.exe -m mypy --strict` | 0 | `Success: no issues found in 10 source files` |
| `.venv/Scripts/python.exe -m pytest -q` | 0 | `5 passed in 1.12s` |
| `npm.cmd --prefix frontend run lint` | 0 | ESLint completed with `--max-warnings 0` |
| `npm.cmd --prefix frontend run typecheck` | 0 | `tsc --noEmit` completed |
| `.venv/Scripts/python.exe -m alembic upgrade head --sql` | 0 | 250 SQL/log lines generated; no server connection or SQL execution |
| `.venv/Scripts/python.exe -m alembic downgrade 0001:base --sql` | 0 | 48 SQL/log lines generated; no server connection or SQL execution |
| `C:/Program Files/Git/bin/bash.exe -n infra/scripts/gate1.sh` | 0 | Bash syntax valid |

Offline SQL generation checks migration rendering only. It proves neither server-side
DDL validity nor a successful migration round trip. Frontend lint/type checks currently
cover the environment contract and tooling; no React application has been implemented.

Earlier checks found long generated DDL source lines, nested-context formatting, and an
untyped SQLAlchemy PostgreSQL dialect constructor. Formatting was corrected without
altering SQL contents or tests; identifier quoting now uses Alembic's existing typed
dialect. Ruff and mypy were rerun successfully. The frozen schema agreement test remains
unchanged in meaning and passes.

### Deviations and reasons

- The generated user-deliverable repository is in `outputs/fintech-platform/`, keeping
  the requested top-level layout intact inside that repository.
- This Windows host has Python 3.13.1; local checks used it. The pinned schema image uses
  Python 3.12.12. Both versions are declared supported, but the image remains unbuilt.
- Only Phase 1 database services and the schema tool are defined in Compose. Full bootstrap,
  API, Streamlit, frontend, nginx, CPU Torch, and pipeline orchestration must be added in
  their later phases after Gate 1 passes. No runtime application stubs were introduced.
- Future `seed`, `gen-types`, and `smoke` Make targets are withheld until their functional
  implementations exist. Empty directories are tracked using `.gitkeep`, not stub code.
- `.env` was not created or committed. Gate resumption begins by copying `.env.example`.
- No live SEC request was made: the optional ingestion check belongs to Phase 2.
- The Phase 1 checkpoint is committed with the gate blocker explicit in its message;
  this commit does not assert phase verification has completed.

## Resume

Install/start Docker with Compose, copy `.env.example` to `.env`, install the locked tools,
and run `bash infra/scripts/gate1.sh` against a disposable development database. Resolve
any actual database/image failures before recording Gate 1 as passed or starting Phase 2.

## Phases 2–6

Not started because Gate 1 is blocked. There are no pipeline datasets, trained models,
metrics, application endpoints, generated API types, user interfaces, or end-to-end
results to report.

## Known limitations

- The full requested application is unfinished and cannot be described as production-ready.
- All live database, container, migration-round-trip, permission, and Cypher checks remain pending.
- The frontend is a tooling skeleton; its current checks do not validate a user interface.
- ESLint 9.39.1 emitted a deprecation/support warning during installation.
- Synthetic-only mule data and free price-source caveats will require documentation once
  those pipelines are actually built; no such inputs or outputs exist in this phase.
