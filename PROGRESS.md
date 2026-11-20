# Build progress

Client date: **2026-11-21 (Asia/Calcutta)**.

## macOS checkpoint (current)

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
