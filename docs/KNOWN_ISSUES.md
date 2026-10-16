# Known issues & backlog

> Purpose: a fix list for future work. Each item says **what happens**, **where it lives** and **how to fix it**, so it can be picked up without re-investigating.
> Status as of 16-Oct-2026. Severity: **High** = wrong or misleading result · **Medium** = robustness / security hardening · **Low** = polish.

## A. Correctness of results

| # | Sev | Issue | Where | Suggested fix |
|---|---|---|---|---|
| A1 | High | **Wrong unit in summary title for percentage columns.** LCR trace shows "USD 150m traced…" although `lcr_pct` is a percentage (150%). The unit is taken from the report table, not from the traced column. | `src/lineage_tracer/tracer.py` (summary title), `report_reader.py` (table unit) | Derive unit per column: `%`/`pct`/`ratio` in column name or glossary term → percent; amounts keep the table unit. Add a test with `lcr_pct`. |
| A2 | High | **Informatica hops show Code-derived although logic is fully known.** Mapping XML contains the complete logic (Expression, Lookup, Aggregator, Filter), but hops with formulas/lookups are treated as "pipeline logic not re-executable". C90: 4 proven / 5 code-derived. Spark hops, by contrast, are replayed from SQL found in the code. Inconsistent trust model. | `src/lineage_tracer/pipelines.py`, `reconcile.py` | Translate mapping transformations to SQL (Source Qualifier → FROM, Lookup → LEFT JOIN, Expression → SELECT expression, Filter → WHERE, Aggregator → GROUP BY/SUM), replay read-only, reconcile like any other hop. Unsupported functions → keep code-derived with the reason. Update `sandbox/expected/c90_fx_delta.json`. |
| A3 | Medium | **Whole-report reconciliation compares whole source tables**, not exactly the reported rows (only a date filter is applied). A total can agree while an individual reported row is wrong. | `reconcile.py` (report mode) | Restrict source totals to the key set of the reported rows (entity × portfolio, …) via the column lineage of the key columns. |
| A4 | Medium | **Superset virtual dataset joining several tables**: only the first table is traced. | `connectors/superset.py`, `tracer.py` | Use full sqlglot column lineage of the dataset SQL; enqueue every source table. |
| A5 | Medium | **Spark OpenLineage marks every input `DIRECT/IDENTITY`**, even for computed columns. The tracer compensates by parsing Spark SQL strings in the job source; DataFrame-API-only logic falls back to "computed from … (Spark)" and totals-only reconciliation. | `pipelines.py` (OpenLineage handling) | Parse PySpark DataFrame expressions (AST of the `.withColumn/.select` calls) or require jobs to keep transformations in Spark SQL; never treat IDENTITY as identity when a column has >1 input. |
| A6 | Low | **Business rules show raw column names** when a column has no glossary comment (`market_value`, `cpty_id`, `entity_key`); one rule still prints `rating_grade = COALESCE(rating_grade, 'NR')`. | `business_rules.py` | Humanise names (`cpty_id` → "counterparty id"), render COALESCE as "defaulting to 'NR' when missing"; add glossary comments for remaining columns. |
| A7 | Low | **Report title matching**: the Superset chart is found by the uploaded report's title; if they differ, the user must type the chart name. | `connectors/superset.py` | Fuzzy match + show candidate charts to pick from. |

## B. Robustness

| # | Sev | Issue | Where | Suggested fix |
|---|---|---|---|---|
| B1 | Medium | **Trace fails with `KeyError: 'result'` if Superset is still starting** (e.g. right after WSL wakes). | `connectors/superset.py` | Retry with back-off on 5xx/missing `result`; surface status "source not ready" instead of failing. |
| B2 | Medium | **Running trace is not resumed after an API restart** (paused traces do resume). | `tracer.py`, `api.py` | On startup, re-queue traces in status `running`; make steps idempotent. |
| B3 | Medium | **Query history is harvested only on demand** (`POST /api/tracer/harvest`); `pg_stat_statements` evicts/resets in between. | `harvest.py` | Scheduled harvest (every 1–2 h, as OpenMetadata recommends); raise `pg_stat_statements.max` to ≥ 10 000. |
| B4 | Medium | **Server-log evidence reads only the 8 newest csvlog files** (~10 s cold); after rotation old runs disappear. | `pipelines.py` (`server_log`) | Ship/harvest log statements continuously into `query_history` (with timestamp, app, user, literal SQL). |
| B5 | Low | Superset chart ids change on every sandbox rebuild; everything looks charts up by title. | `sandbox/*bootstrap*.py` | Make bootstrap update existing charts instead of recreating them. |
| B6 | Low | `sandbox/finlake/build.py` still creates the old `etl.sp_*` procedures; the Spark setup drops them afterwards (order dependency). | `sandbox/finlake/` | Remove procedure DDL from the lake build now that Spark loads the lake. |
| B7 | Low | `TRUNCATE` fails in non-AGE databases on the 5432 cluster (AGE preload hook: "schema ag_catalog does not exist"); all scripts use `DELETE`. | Postgres config | Load AGE per-session (`LOAD 'age'`) instead of `shared_preload_libraries`, or install AGE only in the `lineage` DB's cluster. |
| B8 | Low | Python `SyntaxWarning` for `"\S"` escapes in docstrings of `sandbox/pipelines/{informatica,spark}/verify.py`. | those files | Raw strings. |

## C. Security & operations (must fix before any non-demo use)

| # | Sev | Issue | Where | Suggested fix |
|---|---|---|---|---|
| C1 | High | **No real authentication**: demo role switcher (`X-Role` header) only. Anyone who can reach the API can trace, reveal (as analyst) and export. | `src/lineage_api/roles.py`, `web/` | SSO (OIDC) + server-side roles; at minimum an API token for any exposed deployment. |
| C2 | High | **`lineage_ro` has `pg_read_server_files`** (to read csvlog) — can read any file the DB server can. | `sandbox/pipelines/lcr/configure_log.sh` | `SECURITY DEFINER` function that only reads `log/*.csv`, or ship logs instead of reading files from SQL. |
| C3 | Medium | **Vault key handling**: key in `.vault.key` per checkout; two checkouts sharing one `lineage` DB produced undecryptable (stale) credentials. | `src/lineage_tracer/vault.py` | Key from a secret store / env only; key id stored with each credential; rotation command. |
| C4 | Medium | Sandbox credentials in plain text (`connections.xml`, scripts, Superset `SECRET_KEY`). Dev-only, but public in the repo. | `sandbox/` | Read from env/.env (git-ignored) with documented defaults. |
| C5 | Low | Credentials of other systems on the same host are tried automatically (by design, audited). In production this should be policy-controlled. | `vault.py`, `tracer.py` | Config flag + allow-list per host. |

## D. Lineage repository (Apache AGE) — convergence

| # | Sev | Issue | Where | Suggested fix |
|---|---|---|---|---|
| D1 | Medium | **Trace results are only partly in the graph.** Tracer hops, statuses, evidence and business rules live in relational tables (`trace_hop`); only discovered column edges are written to AGE (`persist_graph`), without status, evidence or validity dates, and best-effort (errors swallowed). | `tracer.py` (`persist_graph`), `lineage_store/ingest_sql.py` | Write hop status, pipeline type, evidence reference and `valid_from/valid_to` onto DERIVES edges; Job vertices per pipeline run; make the graph the single source for "current lineage" queries. |
| D2 | Medium | **Explorer (`/explorer`) runs on seeded demo data**, separate from what the Tracer discovers. | `src/lineage_store/seed/` | Build Explorer screens from tracer-discovered graph + run facts. |
| D3 | Low | Dataset-level `READS/WRITES` edges (Dataset↔Job) are defined in the model but not populated; pipeline jobs are represented only through `job_id` on column edges. | `ingest_ol.py`, mapping ingest | Create Job vertices + READS/WRITES for every pipeline run (OpenLineage model). |
| D4 | Low | Forward lineage (impact) in the Tracer is not implemented (Explorer has a seeded version). | `tracer.py` | Same scanners inverted (consumers), or graph traversal once D1 is done. |

## E. UI polish

| # | Sev | Issue | Suggested fix |
|---|---|---|---|
| E1 | Low | Large graphs (20+ tables) are small at "Fit"; zoom floor 0.7 pans to the anchor. | Group by schema/layer, collapse off-path nodes by default. |
| E2 | Low | React Flow attribution label visible. | Keep (licence) or React Flow Pro. |
| E3 | Low | A failed trace shows a minimal card. | Show step-level error and a retry button. |

## F. Model simplifications in the sandbox (not bugs, documented for reviewers)
- LCR: Basel Level 2A/2B caps (40% / 15%) not applied.
- C 07.00 column semantics simplified (0220 = rated portion).
- FX restatement and collateral revaluation are injected on purpose to demonstrate *code-derived* hops.
