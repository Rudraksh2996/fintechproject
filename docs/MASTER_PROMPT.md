# MASTER PROMPT: Dual-Engine FinTech Threat & Signal Platform

You are a senior full-stack engineer and ML engineer working autonomously in this repository. Build, containerize, and verify a production-grade monorepo for a **Dual-Engine FinTech Threat & Signal Platform** with two modules:

1. **Insider Cluster Buy Radar**: detects public-market alpha from clusters of insider open-market or private purchases (code P) (SEC Form 4).
2. **Money Mule Ring Detector**: finds coordinated money-laundering / mule rings in a temporal transaction graph.

Both modules sit behind one **FastAPI gateway**. They are visualized in a **React + Three.js 3D command center**, with a companion **Streamlit Quant Workbench** for analysts.

Read this whole document, including **Section 10 (Amendments)**, before writing code. Section 10 overrides earlier sections where they conflict. Work through the phases in order. **Do not start a phase until the previous phase's verification gate passes.** If a gate fails, fix the root cause. Never weaken a test, skip a check, or fake an output to get past a gate.

---

## 0. OPERATING RULES (READ FIRST, APPLY ALWAYS)

### 0.1 Non-negotiable guardrails
- **No placeholders.** No `TODO`, `pass`, `NotImplementedError`, `...` bodies, "lorem ipsum", or hard-coded mock JSON in the frontend. Every UI element shows data that comes from the real backend, which reads real databases or model outputs.
- **No frontend-only mocks.** The React app must never import fixture JSON for display. If data is missing, show a proper empty state or error state.
- **Demo mode is real, not mocked.** `DEMO_MODE=true` means the real pipelines run on bundled, clearly labeled **synthetic** inputs: synthetic Form 4 XML fixtures, the synthetic transaction generator, and synthetic price series. These inputs go through the exact same parsers, detectors, databases, model, and API as live mode. The only difference is the data source.
- **Type safety end to end.**
  - Python: full type hints, Pydantic v2 models for every request and response, and `mypy --strict` passing on `backend/`, `edgar_pipeline/`, and `ml_pipeline/`.
  - TypeScript: `strict: true`, no `any` (enforced by ESLint `@typescript-eslint/no-explicit-any: error`).
  - API types for the frontend are **generated** from FastAPI's OpenAPI schema with `openapi-typescript`. Never hand-write them. A check fails if the generated types are stale.
- **Error handling.** Wrap external I/O (SEC HTTP, Postgres, Neo4j, model loading) in typed exceptions. The API returns RFC 7807-style problem JSON (`{type, title, status, detail}`) and correct status codes. No bare `except:`. Use structured JSON logging with request IDs.
- **Secrets.** Nothing secret goes in the code. Everything comes from environment variables. Commit `.env.example` and never commit `.env`.
- **Determinism.** Every generator, train/test split, and model training run takes a `SEED` (default `42`). The same seed produces byte-identical synthetic datasets.
- **Pinned dependencies.** Python uses `pyproject.toml` plus a lockfile (`uv`). Node uses `package-lock.json`. Docker base images are pinned to a minor version.
- **Honesty in the UI.** Label all synthetic data visibly ("SYNTHETIC DEMO DATA"). The Insider Radar shows "Research tool — not investment advice."

### 0.2 Working method
- Keep a running `PROGRESS.md` at the repo root. For each phase, record: what was built, the exact gate commands run, their outputs (summarized), and any deviations with reasons.
- Commit and push at the end of every phase with a message like `phase-N: <summary>`.
- Prefer small, composable modules with unit tests written alongside the code.
- If a library API differs from what this document assumes (because of version drift), check the installed version's documentation and adapt. Note the change in `PROGRESS.md`. Don't stub around it.
- If a gate needs something unavailable in your environment, stop and tell the user the exact command to run. Never skip the gate or fake its output.

---

## 1. SYSTEM ARCHITECTURE

```
                         ┌──────────────────────────────────────────────┐
 Browser ──► nginx :8080 │  /            → React SPA (static build)     │
                         │  /api/*       → FastAPI :8000                │
                         │  /ws/*        → FastAPI :8000 (WS upgrade)   │
                         │  /workbench/* → Streamlit :8501 (WS upgrade) │
                         └──────────────────────────────────────────────┘
                                   │                     │
                        FastAPI gateway             Streamlit Workbench
                   (REST + WebSocket, PyG infer)   (imports edgar_pipeline;
                     │        │          │          writes via FastAPI only)
               PostgreSQL   Neo4j   model artifacts volume
               (insider)   (graph)   (PyG weights, metrics)
                     ▲        ▲          ▲
               edgar_pipeline  ml_pipeline (generator, NetworkX features, GNN training)
```

### 1.1 Resolving the Streamlit ↔ React boundary (implement exactly this)
- **Single origin.** nginx serves everything on port `8080`. Streamlit runs with `--server.baseUrlPath=workbench`. The nginx config must proxy WebSocket upgrades for `/workbench/_stcore/stream` and `/ws/`. This avoids CORS and cookie problems and lets the iframe embed work.
- **React owns** the operational command center: the live alert feed, the 3D Radar, and the 3D Mule Explorer.
- **Streamlit owns** analyst research: threshold tuning, backtests, raw Form 4 inspection, and CSV export.
- **One source of truth for logic.** The cluster detection engine and conviction scoring live **only** in `edgar_pipeline/` as an installable package. Both the backend and Streamlit import it, so the two UIs can never compute different answers.
- **Data access rules for Streamlit:**
  - Reads come from Postgres through a dedicated **read-only role** (`workbench_ro`).
  - Writes (saving a threshold config as active, triggering a re-detection) go **only** through FastAPI endpoints.
- **React access to Streamlit.** React has a "Quant Workbench" nav item that renders Streamlit in a full-height `<iframe src="/workbench/">` with an "Open in new tab" button. Pages deep-link with query params, for example `/workbench/?ticker=XYZ&alert_id=123`, which Streamlit reads through `st.query_params`.

### 1.2 Live alerts
- When a row is inserted into `cluster_alerts`, a Postgres trigger runs `pg_notify('cluster_alerts', <alert_id>)`.
- FastAPI holds one async `LISTEN` connection (asyncpg). It fetches the full alert and broadcasts it to all `/ws/alerts` clients as a typed message.
- The mule module publishes `ring_detected` and `account_scored` events on `/ws/mule` the same way, using an in-process async pub/sub fed by the scoring service.
- WebSocket messages are a discriminated union validated by Pydantic:
  ```json
  {"type": "cluster_alert", "version": 1, "payload": {...}}
  {"type": "ring_detected", "version": 1, "payload": {...}}
  {"type": "heartbeat", "version": 1, "ts": "..."}
  ```
  The server sends a heartbeat every 15 s. The client auto-reconnects with exponential backoff.

---

## 2. EXACT MONOREPO STRUCTURE

Use this layout. You may add files but must not rename top-level directories.

```
.
├── README.md
├── PROGRESS.md
├── Makefile                      # up, down, seed, test, lint, typecheck, gen-types, smoke
├── docker-compose.yml
├── .env.example
├── .gitattributes                # *.sh, *.sql, *.cypher, Dockerfiles: text eol=lf
├── docs/MASTER_PROMPT.md         # this file
├── infra/
│   ├── nginx/nginx.conf
│   ├── postgres/init/00_roles.sql
│   ├── neo4j/constraints.cypher
│   ├── docker/                   # Dockerfiles: backend, streamlit, frontend, bootstrap
│   └── scripts/ (bootstrap.sh, wait_for.sh, gate1.sh … gateN.sh, smoke_test.sh)
├── edgar_pipeline/               # installable package: edgar_pipeline
│   ├── pyproject.toml
│   ├── src/edgar_pipeline/
│   │   ├── config.py, http_client.py, discovery.py, form4_parser.py, models.py
│   │   ├── db/ (models.py, repository.py), migrations/   # SQLAlchemy 2.0 + Alembic
│   │   ├── cluster_engine.py, conviction.py, backtest.py, prices.py
│   │   ├── fixtures/             # synthetic Form 4 XML + synthetic prices (demo)
│   │   └── cli.py                # `edgar ingest|detect|backfill|seed-demo`
│   └── tests/
├── ml_pipeline/                  # installable package: ml_pipeline
│   ├── pyproject.toml
│   ├── src/ml_pipeline/
│   │   ├── config.py
│   │   ├── generator/
│   │   ├── neo4j_store/ (loader.py, queries.py)
│   │   ├── features/ (networkx_features.py, temporal.py, communities.py)
│   │   ├── gnn/ (dataset.py, model.py, train.py, evaluate.py, infer.py)
│   │   ├── scoring.py
│   │   └── cli.py                # `mule generate|load|features|train|evaluate|score`
│   └── tests/
├── backend/
│   ├── pyproject.toml
│   ├── src/app/
│   │   ├── main.py, settings.py, errors.py, deps.py
│   │   ├── api/v1/ (insider.py, mule.py, system.py, config.py)
│   │   ├── ws/ (alerts.py, mule.py, hub.py)
│   │   ├── schemas/
│   │   └── services/ (insider_service.py, mule_service.py, inference_service.py)
│   └── tests/
├── streamlit_workbench/
│   ├── pyproject.toml, app.py
│   ├── pages/ (1_Threshold_Tuner.py, 2_Backtester.py, 3_Form4_Inspector.py, 4_Exports.py)
│   ├── .streamlit/config.toml
│   └── tests/
└── frontend/
    ├── package.json, vite.config.ts, tsconfig.json, tailwind.config.ts, eslint config
    ├── src/
    │   ├── api/ (client.ts, generated/schema.d.ts, hooks/)
    │   ├── ws/useLiveChannel.ts
    │   ├── routes/ (CommandCenter, InsiderRadar, MuleExplorer, Workbench)
    │   ├── components/ (layout/, insider/, mule/, ui/)
    │   ├── three/ (RadarScene.tsx, MuleGraph3D.tsx, particles/, materials/)
    │   └── lib/ (format.ts, colorScales.ts)
    └── tests/ (vitest unit, playwright e2e)
```

---

## 3. MODULE 1: INSIDER CLUSTER BUY RADAR (Python, SEC EDGAR, Pandas, PostgreSQL, Streamlit)

### 3.1 SEC EDGAR ingestion with fair access
- **HTTP client** (`httpx` async):
  - Every request sends `User-Agent: ${SEC_USER_AGENT}`, which must look like `"CompanyName contact@email.com"`. If this is unset in live mode, refuse to start.
  - Also send `Accept-Encoding: gzip, deflate`.
  - Rate limiting uses a shared async token bucket of **≤ 10 req/s globally**. The default is 8 req/s and is configurable but **capped at 10 in code**.
  - Retries: exponential backoff with jitter (`tenacity`) on 429, 5xx, and timeouts. Honor `Retry-After`. Max 5 attempts.
  - Treat a 403 as possible fair-access blocking: log loudly and pause.
  - Cache raw responses on disk, keyed by URL.
- **Discovery:** find Form 4 / 4/A filings over a date range using EDGAR's daily or quarterly form indexes under `https://www.sec.gov/Archives/edgar/`. Supported modes:
  - by date range across all issuers;
  - per ticker/CIK via `https://data.sec.gov/submissions/CIK##########.json`, with ticker→CIK mapping from `https://www.sec.gov/files/company_tickers.json`.
  
  Resolve each filing to its primary Form 4 XML document.
- **Parser** (`lxml`, `ownershipDocument` schema). Extract:
  - issuer: `issuerCik`, `issuerName`, `issuerTradingSymbol`;
  - each `reportingOwner`: `rptOwnerCik`, `rptOwnerName`, and relationship flags `isDirector`, `isOfficer`, `isTenPercentOwner`, `isOther`, plus `officerTitle`;
  - per `nonDerivativeTransaction`: `transactionDate`, `transactionCoding/transactionCode`, `transactionShares`, `transactionPricePerShare`, `transactionAcquiredDisposedCode`, `sharesOwnedFollowingTransaction`, `directOrIndirectOwnership`, footnote references;
  - the Rule 10b5-1 indicator (`aff10b5One`) when present.
  
  Handle these cases: missing values, footnote-only prices, multiple reporting owners, 4/A amendments (the amendment supersedes the original row set), and namespace or whitespace variations. A malformed filing is quarantined to a `parse_errors` table. It must not crash the batch.
- **Normalization and filtering:**
  - Keep only `nonDerivativeTable` rows with `transactionCode == 'P'` and `acquiredDisposed == 'A'`.
  - Explicitly exclude `A` (grants), `M` (option exercises), `F` (tax withholding), and all other codes. Unit tests cover each exclusion.
  - Insider scope defaults to officers and directors. Pure 10% owners are excluded by default (`include_ten_percent_owners=false`).
  - `value_usd = shares × price`. Rows with no usable price are excluded from dollar thresholds and flagged.
  - `pct_holdings_increase = shares / max(post_shares - shares, ε)`. A brand-new position is capped at `new_position_pct` (default 1.0) and flagged `is_new_position`.

### 3.2 PostgreSQL schema (SQLAlchemy 2.0 + Alembic)
**Core tables (required):**
- `companies(id PK, cik UNIQUE NOT NULL, ticker, name, created_at, updated_at)`
- `insiders(id PK, cik UNIQUE NOT NULL, name, created_at)`
- `form4_transactions`:
  - columns: `id PK`, `accession_number NOT NULL`, `line_number NOT NULL`, `company_id FK`, `insider_id FK`, `ticker` (denormalized), `transaction_date DATE NOT NULL`, `filing_date DATE NOT NULL`, `transaction_code CHAR(1)`, `shares NUMERIC`, `price NUMERIC`, `value_usd NUMERIC`, `shares_owned_after NUMERIC`, `pct_holdings_increase NUMERIC`, `is_director BOOL`, `is_officer BOOL`, `officer_title TEXT`, `is_csuite BOOL`, `is_10b5_1 BOOL`, `is_amendment BOOL`, `superseded BOOL DEFAULT false`, `raw_xml_url TEXT`, `ingested_at`
  - **`UNIQUE(accession_number, line_number)`** for deduplication. Ingestion uses `INSERT … ON CONFLICT`.
  - **Index `(ticker, transaction_date)`**, plus `(company_id, transaction_date)` and `(filing_date)`.
- `cluster_alerts`:
  - columns: `id PK`, `company_id FK`, `ticker`, `window_start`, `window_end`, `first_filing_date`, `alert_filing_date`, `n_insiders`, `n_csuite`, `total_value_usd`, `avg_pct_holdings_increase`, `conviction_score NUMERIC(5,2)`, `score_breakdown JSONB`, `config_id FK`, `status` (`new|acknowledged|dismissed`), `created_at`
  - `UNIQUE(company_id, window_start, config_id)`

**Supporting tables:**
- `form4_filings(accession_number UNIQUE, …)`
- `cluster_alert_members(alert_id, transaction_id)`
- `detection_configs` (versioned; exactly one `is_active`)
- `ingestion_runs`
- `parse_errors`
- `price_bars(ticker, date, close, source)`

Add the `pg_notify` trigger on `cluster_alerts` insert. Create the `workbench_ro` role with `SELECT` only.

### 3.3 Pandas cluster detection engine
- **Config:** `window_days` (default **14**), `min_insiders` (default **3**), `min_insider_value_usd` (default 25,000), `min_cluster_value_usd` (default 100,000), `include_ten_percent_owners`, `exclude_10b5_1` (default false; flag only).
- **Algorithm:**
  1. Group by issuer CIK.
  2. Sort by transaction date and run a time-based rolling window.
  3. Within each window, sum value per distinct insider and keep only insiders at or above `min_insider_value_usd`.
  4. Trigger when the count of distinct qualifying insiders is at least `min_insiders` and the qualifying total is at least `min_cluster_value_usd`.
  5. **Merge overlapping or adjacent triggering windows** for the same issuer into one alert.
  6. Make it idempotent: re-running with the same config upserts and never duplicates.
- **Look-ahead safety:** `alert_filing_date` is the **filing date** of the transaction that first satisfied the trigger. Backtests must enter on or after it.
- Detection over 100k transactions must finish in under 10 s (add a benchmark test).

### 3.4 Conviction Score, documented and deterministic, range 0–100
```
f_buyers   = min(1, (n_insiders - min_insiders + 1) / (cap_insiders - min_insiders + 1))   # cap_insiders default 8
f_csuite   = min(1, (2*n_ceo_cfo + n_other_csuite) / 3)          # C-suite parsed from officerTitle via regex map
f_value    = clip(log10(total_value_usd / min_cluster_value_usd) / log10(value_cap_multiple), 0, 1)   # default 100
f_holdings = clip(median_pct_holdings_increase / holdings_cap, 0, 1)                    # holdings_cap default 0.5
score = 100 * (w_b*f_buyers + w_c*f_csuite + w_v*f_value + w_h*f_holdings)
defaults: w_b=0.30, w_c=0.25, w_v=0.25, w_h=0.20  (weights validated to sum to 1)
```
Store every component in `score_breakdown`. Weights live in `detection_configs`. Unit-test the boundary values.

### 3.5 Prices and backtesting
- Define a `PriceProvider` protocol.
  - **Live:** Stooq CSV, with yfinance as fallback, cached in `price_bars`.
  - **Demo:** bundled synthetic GBM series plus a synthetic benchmark, all tagged `source='synthetic'`.
- Enter at the close on the first trading day ≥ `alert_filing_date`. Compute forward returns at +5, +20, and +60 trading days, both absolute and excess over the benchmark (`SPY` in live mode).
- Report: hit rate, mean and median excess return, the distribution, and results by conviction-score quintile.

### 3.6 Demo fixtures
Generate **synthetic Form 4 XML files** that follow the real `ownershipDocument` schema, for about 40 fictional issuers with fictional tickers over 18 months. The data includes:
- planted strong and borderline clusters;
- noise: lots of `A`, `M`, and `F` codes, sales, single-insider buys, and 10% owner buys;
- at least two 4/A amendments;
- one deliberately malformed file.

Never use real company or person names. In demo mode, a **replay scheduler** feeds fixture filings through the real ingestion → detection path in chronological batches, so alerts appear live over WebSocket.

### 3.7 Streamlit Quant Workbench
Dark theme. Sidebar link back to `/`. Pages:
1. **Threshold Tuner:** sliders for all config values and weights. Runs `cluster_engine` live on data read with the read-only role. Shows a diff against the active config. Has "Save as new config" and "Activate" buttons, both calling FastAPI.
2. **Backtester:** pick a config and date range. Shows the summary, distributions, and quintile chart (Plotly).
3. **Form 4 Inspector:** search by ticker, insider, or accession number. Shows parsed rows, a link to the SEC filing (live mode), and the raw XML.
4. **Exports:** CSV downloads of alerts, members, and backtest results.

Respect the `?ticker=` / `?alert_id=` query params.

---

## 4. MODULE 2: MONEY MULE RING DETECTOR (Python, NetworkX, PyTorch, PyG, Neo4j)

### 4.1 Synthetic financial-crime generator
- **Scale presets:** `lite`, `demo`, and `full`. See Section 10 for `lite`, which is the default.
  - `demo`: about 8k accounts and about 120k transactions over 90 days.
  - `full`: about 50k accounts and about 1M transactions.
- **Background legitimate behavior:**
  - account types: retail, business, merchant, payroll;
  - lognormal amounts and diurnal/weekly seasonality;
  - salary deposits followed by bills and merchant spend;
  - P2P transfers in small-world friend graphs;
  - realistic shared devices and IPs.
- **Injected labeled typologies.** Each ring gets a `ring_id` and `typology`; parameters are randomized per ring.
  - **Fan-in / fan-out dispersion.**
  - **Rapid pass-through chains:** 3–7 hops with a short hold time and a small skim per hop.
  - **Cyclic layering loops:** 3–6 accounts.
  - **Smurfing / structuring:** repeated deposits just below `REPORTING_THRESHOLD` (default 10,000).
  - **Shared device, IP, and beneficiary metadata** well beyond the background rate.
- **Realism and difficulty:**
  - mules also do normal transactions (camouflage);
  - **hard negatives** that look suspicious but are legitimate: payroll fan-out, merchant fan-in, family money loops;
  - label noise is configurable.
  - Target prevalence: about 1–3% of accounts are mules.
- **Output:** Parquet tables plus a `manifest.json` with seed, parameters, and a hash.

### 4.2 Neo4j graph store and Cypher forensics
- **Model:**
  - nodes: `(:Account {account_id, type, created_at, home_country})`, `(:Device {device_id})`, `(:IP {ip})`;
  - edges: `(:Account)-[:TRANSFERRED {txn_id, amount, ts, channel}]->(:Account)`, `[:USED_DEVICE]`, `[:LOGGED_FROM]`.
  - **Ground-truth labels** are stored separately and **never** read by feature or inference code; tests enforce this.
- **Constraints and indexes:** uniqueness on all IDs, and a relationship property index on `TRANSFERRED.ts`.
- **Loading:** batched `UNWIND $rows AS r MERGE …`, idempotent.
- **Parameterized queries.** Variable-length path bounds **cannot be Cypher parameters**, so validate `k` against an int whitelist (1–6) before interpolating it. Everything else must be `$params`.
  1. High-velocity subgraph within `[$t0, $t1]`.
  2. **Time-respecting k-hop money trail**: `ALL(i IN range(0, size(rels)-2) WHERE rels[i].ts <= rels[i+1].ts AND rels[i+1].ts - rels[i].ts <= $max_gap)`.
  3. Pass-through hubs: outflow ≈ inflow and short median hold time.
  4. Shared-infrastructure clusters.
  5. Capped ego-network fetch for the 3D explorer.

### 4.3 NetworkX structural and temporal features
- **Per-account features:**
  - weighted PageRank;
  - betweenness (`k`-sample approximation);
  - in/out degree and flow totals, `in_out_flow_ratio`;
  - SCC size, and the count of simple cycles of length ≤ 6;
  - hold time median and p10;
  - burstiness `B = (σ - μ) / (σ + μ)` of inter-transaction times;
  - share of amounts in `[0.9·threshold, threshold)`;
  - shared-device and shared-IP degree;
  - account age.
- **Community detection:** seeded Louvain on the undirected weighted projection plus the shared-infrastructure edges. These communities are the **candidate rings**.
- Persist features to Parquet and expose them through the API.

### 4.4 PyTorch Geometric GNN
- **Data:** node features are standardized NetworkX features plus account-type one-hot. Edge attributes are log amount, hour sin/cos, and inter-hop gap.
- **Models:**
  - `GraphSAGE` (default, inductive, for real-time scoring of new nodes);
  - `GATv2Conv` with `edge_dim`.
  
  Use 2–3 layers with a binary head.
- **Training:**
  - **ring-disjoint train/val/test split**;
  - class-weighted BCE or focal loss;
  - early stopping on validation PR-AUC;
  - `NeighborLoader`;
  - CPU only.
- **Metrics** (`artifacts/metrics.json`): PR-AUC, ROC-AUC, precision@k, recall at 1% FPR, and per-typology recall, plus a feature-only **baseline** (logistic regression or gradient boosting).
- **Ring Risk Score** (0–100): `100 × (0.6·mean(top-k member probs) + 0.2·structural_factor + 0.2·shared_infra_factor)`, with a stored breakdown.
- **Artifacts:** `model.pt`, `model_config.json`, `feature_scaler.json`, `metrics.json`, `scores.parquet` on a shared volume.
- **Inference service:**
  - batch scoring of all accounts;
  - `POST /api/v1/mule/transactions` ingests new transfers, recomputes local k-hop features, runs the GNN on the subgraph, and emits WS events when scores cross `RISK_ALERT_THRESHOLD`.

---

## 5. FASTAPI GATEWAY: API CONTRACT (`/api/v1`)

**System**
- `GET /health` → `{status, postgres, neo4j, model_loaded, demo_mode, version}`
- `GET /system/info`

**Insider**
- `GET /insider/alerts?ticker&min_score&from&to&status&limit&cursor`
- `GET /insider/alerts/{id}`
- `PATCH /insider/alerts/{id}`
- `GET /insider/companies/{ticker}/transactions?from&to`
- `GET /insider/radar?from&to`
- `GET /insider/configs`, `POST /insider/configs`, `POST /insider/configs/{id}/activate`
- `POST /insider/detect` and `GET /insider/jobs/{id}`
- `POST /insider/ingest` (returns 409 in demo mode unless explicitly allowed)

**Mule**
- `GET /mule/rings?min_risk&typology&limit`
- `GET /mule/rings/{ring_id}/graph?t0&t1` → `{nodes, links, truncated}`
- `GET /mule/accounts/{id}`
- `GET /mule/accounts/{id}/trail?k&direction&t0&t1`
- `GET /mule/graph/overview?t0&t1&max_nodes`
- `GET /mule/timeline?ring_id`
- `POST /mule/transactions`
- `GET /mule/model/metrics`
- `GET /mule/ground-truth/{ring_id}` (demo only)

**WebSocket:** `/ws/alerts` and `/ws/mule`.

**Cross-cutting:** CORS locked to the nginx origin; request IDs; DB timeouts; async Neo4j driver and asyncpg pool. `make gen-types` exports `backend/openapi.json` and regenerates `frontend/src/api/generated/schema.d.ts`.

---

## 6. FRONTEND: REACT + THREE.JS COMMAND CENTER

**Stack:** Vite, React 18, TypeScript strict, Tailwind, TanStack Query, React Router, Zustand, `three`, `@react-three/fiber`, `@react-three/drei`, `react-force-graph-3d`, and Recharts or visx.

**Design:** dark institutional theme, monospace numerals, accessible, with loading, empty, and error states everywhere.

### 6.1 Unified Command Center
- Left nav: Command Center, Insider Cluster Radar, Money Mule Explorer, Quant Workbench (iframe).
- Top bar: status of both WebSockets, data-provenance badge, and model version.
- Landing page: KPI tiles, a combined live event feed, and previews of each module.

### 6.2 3D Money Mule Network Explorer
- Node size from log volume; node color on a risk scale from the GNN probability, with a legend.
- **Animated directional particles** whose speed and count scale with amount and recency.
- Orbit, zoom, and pan; focus on a node; reset the camera.
- **Click-to-inspect forensics sidebar** with features, probability breakdown, ring, shared infrastructure, counterparties, and a k-hop trail highlight.
- **Ring isolation filter.**
- **Time-window scrubber** with play/pause replay and a flow histogram.
- Render at most 3,000 nodes, at 50+ FPS on demo ring views.

### 6.3 3D Insider Cluster Radar
- R3F constellation/radar view:
  - radius or height = conviction;
  - angle = recency;
  - size = log USD;
  - intensity = insider count;
  - animated sweep, tooltips, and a pulse when a new WS alert arrives.
- **Live alert feed** with acknowledge and dismiss actions.
- **Drill-down drawer:** per-insider Form 4 trades, score breakdown, SEC link, and a Workbench deep link.

---

## 7. DOCKER COMPOSE ORCHESTRATION

Services:
- `postgres` (`postgres:16`)
- `neo4j` (`neo4j:5-community`)
- `bootstrap`: one-shot and idempotent. Runs migrations → constraints → seed fixtures → detect → generate graph → load → features → train → score.
- `backend`: depends on bootstrap via `service_completed_successfully`.
- `streamlit`: `baseUrlPath=workbench`, uses `workbench_ro`.
- `frontend`: multi-stage node → nginx on **8080**, proxying `/api`, `/ws`, and `/workbench` with WS upgrade headers.

Every service has a healthcheck. Python images use CPU-only torch. Volumes: `pgdata`, `neo4jdata`, `artifacts`, `edgar_cache`. `.env.example` documents every variable. `cp .env.example .env && docker compose up --build` must produce the full working demo at `http://localhost:8080` with no manual steps.

---

## 8. PHASED BUILD PLAN WITH VERIFICATION GATES

### Phase 1: Infra and schemas
**Gate 1:**
- postgres and neo4j become healthy;
- Alembic `up → down → up` round-trip succeeds;
- the unique constraint and `(ticker, transaction_date)` index exist;
- `workbench_ro` cannot INSERT;
- the notify trigger exists;
- Neo4j constraints exist;
- ruff and `mypy --strict` pass.

### Phase 2: EDGAR ingestion and Postgres
**Gate 2:** `pytest edgar_pipeline` passes, covering:
- rate limit ≤ 10 req/s, measured;
- User-Agent enforcement;
- retry/backoff;
- the parser, including multi-owner, 4/A, and quarantine;
- exclusion of A, M, F, and S;
- dedup on re-ingest;
- cluster boundaries (2 insiders → none, 3 → alert, day 15 falls outside, windows merge);
- score bounds;
- no look-ahead in the backtester;
- the 100k-row benchmark under 10 s.

In addition, `edgar seed-demo && edgar detect` must find the planted clusters and not the traps. The live EDGAR check is optional; if offline, record "skipped, offline".

### Phase 3: Synthetic data, Neo4j, NetworkX, and PyG
**Gate 3:**
- `pytest ml_pipeline` passes, covering:
  - generator determinism;
  - typology signatures;
  - Cypher correctness on toy graphs, including the time-respecting trail;
  - `k` injection is rejected;
  - feature correctness;
  - no label leakage.
- The full CLI pipeline completes.
- Test-split GNN PR-AUC ≥ 0.75, compared against the baseline and reported honestly.
- Ring Risk top-10 precision is reported.

### Phase 4: FastAPI gateway and Streamlit
**Gate 4:**
- `pytest backend` passes with ≥ 80% coverage against real DB and Neo4j instances;
- `mypy --strict` passes;
- the health check reports `model_loaded: true`;
- list endpoints return non-empty data, and a bad ID returns a 404 problem+json;
- a WS client receives a `cluster_alert` within 10 s of a replay batch;
- `POST /mule/transactions` produces an `account_scored` event;
- the Streamlit health endpoint is ok and AppTest passes on all pages;
- activating a config in the Tuner shows up in the API;
- regenerating `gen-types` leaves the diff clean.

### Phase 5: React + Three.js UI
**Gate 5:**
- `npm run lint && npm run typecheck && npm run test && npm run build` all pass;
- there are no mocks, fixtures, or lorem ipsum in display code;
- vitest covers the color scale, scrubber filtering, WS parsing and reconnect, and formatters;
- all routes render through nginx.

### Phase 6: End-to-end smoke tests and hardening
**Gate 6:**
1. Starting from `docker compose down -v`, a fresh `up --build` becomes healthy with no manual steps.
2. `make smoke` passes.
3. Playwright (headless Chromium with SwiftShader WebGL) passes:
   - KPIs show data;
   - clicking a Radar node opens the drawer;
   - a live alert appears;
   - the Mule graph renders and its sidebar opens;
   - the ring filter isolates a ring;
   - moving the scrubber changes the edge count;
   - the Workbench iframe loads.
4. `make lint typecheck test` passes.
5. `PROGRESS.md` contains the final outputs and known limitations.

---

## 9. DEFINITION OF DONE
- `docker compose up` on a clean machine produces a fully working, data-rich demo at `http://localhost:8080` with live alerts. Every view is backed by real pipeline outputs.
- All six gates pass and are documented in `PROGRESS.md`.
- No placeholders, no frontend mocks, strict typing throughout, and API types in sync.
- Live EDGAR mode works by setting `DEMO_MODE=false` and a valid `SEC_USER_AGENT`, within SEC fair-access limits.

---

## 10. AMENDMENTS (override earlier sections where they conflict)

### 10.1 Target dev machine
The primary machine is an Apple M4 Mac with 16 GB RAM. Docker runs through OrbStack or Docker Desktop, with at least 6 GB allocated to Docker. Requirements:
- All images must run natively on `linux/arm64`. Never hard-code `platform: linux/amd64`.
- CPU-only torch must resolve for aarch64 inside the containers.
- The stack must also run on an 8 GB Windows + WSL2 machine with about 5 GB available to Docker. Keep the resource limits below.

### 10.2 Resource limits
- Neo4j: heap max 512m, pagecache 256m. Postgres: `shared_buffers=128MB`.
- Every compose service has a `mem_limit`. The total of the long-running services must stay under 4 GB.
- Add `MULE_SCALE=lite` (about 3k accounts and about 40k transactions over 60 days) as the **default** in `.env.example`. `demo` and `full` remain available.
- GNN training runs **only** in the one-shot `bootstrap` container, and must finish in under 5 minutes on 4 CPU threads. Set `TORCH_NUM_THREADS` from env.
- The backend loads the model for inference only and never trains.
- Use multi-stage Dockerfiles to keep images small.
- Playwright runs under `docker compose --profile e2e`, not as a long-running service.

### 10.3 Host toolchain
- The repo requires Python `>=3.12,<3.14`. If the host Python is outside that range, run `uv python install 3.13`, use it through `uv` (`uv sync`, `uv run`), and pin it in `.python-version`. Never change the global system Python.
- Node 20 or newer (any current LTS or later works). The frontend Docker build pins `node:22-alpine`.
- Add `.gitattributes` forcing LF endings for `*.sh`, `*.sql`, `*.cypher`, and Dockerfiles.

### 10.4 Gate scripts
Each phase gets an `infra/scripts/gateN.sh` that runs that phase's checks and exits non-zero on any failure. Gate checks verify the **definitions** of constraints and indexes (their columns and uniqueness), not just that objects with the right names exist.

### 10.5 Session resumption
Every new session starts by reading this file and `PROGRESS.md`. It resumes at the first phase whose gate hasn't passed. Before stopping for any reason, update `PROGRESS.md` with the exact next steps.