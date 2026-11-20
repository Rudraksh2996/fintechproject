# Dual-Engine FinTech Threat & Signal Platform

**Status: Phase 1 infrastructure and schemas are implemented. Gate 1 is blocked by
the absence of Docker in the authoring environment. Phases 2–6 have not started.**
This repository does not yet serve a command center or run ingestion/model pipelines.
See [PROGRESS.md](PROGRESS.md) for actual verification results.

## Phase 1 setup

Requirements: Docker Engine/Desktop with Compose v2, Python 3.12 or 3.13,
[uv 0.9.11](https://docs.astral.sh/uv/), Node >=22.14, and Bash for the gate script.
GNU Make is optional. Database ports bind to localhost.

```bash
cp .env.example .env
uv sync --all-packages --frozen
cd frontend
npm ci
cd ..
bash infra/scripts/gate1.sh
```

PowerShell can copy the environment file with `Copy-Item .env.example .env`.
Run the Bash script with Git Bash or WSL. `make gate-1` is equivalent.
Use a disposable development database: the required gate includes a migration downgrade
that removes domain tables and data. The script never deletes Docker volumes.

The gate starts Postgres and Neo4j, builds a migration runner, performs
`upgrade head → downgrade base → upgrade head`, applies graph constraints, checks
database permissions and indexes, and runs Python/TypeScript checks. A missing Docker
command exits 127; it cannot produce a successful gate result.

To run just the database services:

```bash
docker compose up -d postgres neo4j
docker compose --profile tools run --build --rm schema
```

Local checks independent of Docker:

```bash
uv run --frozen ruff check .
uv run --frozen mypy --strict
uv run --frozen pytest -q
cd frontend
npm run lint
npm run typecheck
```

## Schema and security

Ten domain tables cover issuers, insiders, raw filings, transactions, versioned configs,
alerts and members, ingestion runs, parse quarantine, and price bars. The initial Alembic
revision contains frozen PostgreSQL DDL independent of future ORM changes. An offline
test checks that this snapshot and the current ORM agree.

Transactions deduplicate on `(accession_number, line_number)` and have the three
required date indexes. Alert inserts call `pg_notify('cluster_alerts', NEW.id::text)`
within the inserting transaction. Delivery consequently happens on commit.

An initial default detection config is inserted. A partial unique index prevents two
active configs; a deferred constraint trigger prevents committing zero active configs.
Thresholds, caps, and scoring weights have database constraints. Activation must update
the old and new configs in one transaction, disabling the old config first.

Postgres initialization creates three distinct roles:

- The environment-supplied admin owns migrations and never serves workbench requests.
- The app role receives SELECT/INSERT/UPDATE/DELETE and sequence usage, without schema creation.
- `workbench_ro` receives SELECT only, no sequence access, and a read-only transaction default.

The live gate deliberately disables the read-only session default before attempting an
INSERT, proving that privileges still reject writes. Passwords come from the environment;
`.env.example` contains local demo credentials that require replacement for deployment.
Role initialization runs only on a fresh Postgres volume; changing environment passwords
does not rotate credentials in an existing database.

Neo4j constraints cover account, device, IP, label account, and transfer identifiers,
with a relationship range index on transfer timestamps. The project uses the syntax in
the [Neo4j 5 constraint manual](https://neo4j.com/docs/cypher-manual/5/constraints/create-constraints/)
and the revision lifecycle described by the
[Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html).

## Intended architecture after all gates pass

```text
Browser → nginx :8080 → React command center
                     → /api + /ws → FastAPI → Postgres + Neo4j + model artifacts
                     → /workbench → Streamlit → read-only Postgres
                                              → FastAPI for writes
```

Only Postgres, Neo4j, and the migration runner are configured in Compose at this phase.
Runtime service Dockerfiles, nginx routing, ingestion, graph generation, GNN training,
the API, workbench pages, and the React UI belong to later gated phases. Their empty
directories establish the requested layout without nonfunctional application code.

## Configuration

Every planned environment variable is documented in `.env.example`. This phase uses
`POSTGRES_*`, `WORKBENCH_RO_PASSWORD`, `NEO4J_AUTH`, and `NEO4J_URI`; the configuration
classes also validate the SEC request-rate cap, live identity, model architecture, and
risk thresholds. PostgreSQL passwords are encoded through SQLAlchemy URL construction.
No credentials are written to `alembic.ini`.

`DEMO_MODE=false` already requires a valid organization/email SEC identity in settings;
live ingestion is not implemented until Phase 2. Synthetic data and model artifacts do
not exist yet. No model metrics or investment signals are claimed.

## Screenshots and walkthrough

Screenshots and a data-rich demo walkthrough will be captured during Phases 5–6 after
the real API and pipelines exist. No UI screenshots are supplied for this infrastructure phase.

## Known limitations

- Gate 1 has not passed; live migrations, grants, and Cypher remain unverified here.
- The complete six-phase application is unfinished, as required by the phase ordering rule.
- The schema tool container has not been built in this environment.
- `make seed`, `make gen-types`, and `make smoke` are added with their actual implementations
  in their respective later phases; no success-returning stand-ins are supplied.
