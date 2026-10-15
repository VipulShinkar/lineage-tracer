# Plan — Lineage Tracer POC (replaces the static explorer screens)

Source of truth: `Reg_Lineage___Journey__Screens_POC_scope_draft_v1.pdf` (3 screens) + the user's "COREP C90 Report" PDF.

## What it does
Upload a regulatory report → pick a data point → name the report source system (Superset or a database) → the tracer **discovers** lineage live, hop by hop, by reading each system's metadata read-only, exactly like OpenMetadata / DataHub ingestion does, and asks for connection details whenever it reaches a system it has no credentials for. Ends at systems of record. Each hop is **Proven** (logic found + value reconciled), **Code-derived** (logic found, not reconciled) or **Unresolved**.

## Discovery loop (per frontier item = system + table + column)
1. **Report source**
   - Superset (REST API, as OpenMetadata `source/dashboard/superset/api_source.py`, DataHub `ingestion/source/superset.py`): login → find chart by report title → chart → dataset (virtual SQL or physical table) → database (backend, host, db). Re-run chart data to locate the selected data point → Proven.
   - Direct DB: user names DB + table/view directly.
2. **Have credentials for that DB?** Vault lookup by (type, host, database). If not → trace pauses `connection_required` with host/db hints → UI asks → resume.
3. **Scan system catalogs for who writes the table/column** (strategies, in order):
   - Views: `pg_views.definition` / `sqlite_master.sql`
   - Functions/procedures: `pg_proc.prosrc` containing `INSERT INTO|UPDATE|MERGE <target>` (record line range)
   - Query log: `pg_stat_statements` (as OpenMetadata `source/database/postgres/queries.py`)
   - SQL → column lineage with sqlglot (reuse `lineage_parser.sql.parser`; DataHub `sql_parsing/sqlglot_lineage.py` pattern)
4. **Cross-system edges**:
   - Foreign tables: `pg_foreign_table` + `pg_foreign_server.srvoptions` (host, dbname) + table options → next system
   - OpenLineage events already received from ETL jobs (existing `POST /api/ingest/openlineage`) → e.g. SQLite market data → staging
   - Otherwise the hop is Unresolved and the user can declare the source
5. **Reconcile**: re-run the discovered SELECT (read-only txn, statement_timeout) filtered to the data point's keys/date and compare with the downstream value (± tolerance) → Proven, else Code-derived.
6. Stop when a table has no writer and no foreign source → **system of record**. Persist every discovered node/edge into the AGE graph (reuse `lineage_store` ingest) + evidence (object name, line range, definition hash, log entry, reconciliation).

## Test estate (sandbox, all inside WSL Ubuntu on D:)
Postgres DBs (one per "system"), read-only user `lineage_ro`, `pg_stat_statements` on, ETL executed once so logs exist:
- **C90 pipeline** (user's report; must reproduce every row: COM DELTA 3916.49 … ALL 9626.96 USD): `trading_db.trade_sensitivity` (system of record, native ccy) → `staging.stg_sensitivity` (via foreign table) → `dwh.dw_sensitivity_usd` (FX to USD, function) → `frtb_engine.calc_sbm_sensitivity` (aggregation by risk_class × sensitivity_type, function) → `reporting_db.rpt_c90_facts` (view/table read by Superset). FX rates: SQLite `market_data.db` → `staging.ref_fx_rates` via an ETL job that emits an OpenLineage event.
- **C 07.00 pipeline** (POC PDF): `loans_db.los.facility` + `collateral_db.col.collateral` + FX → staging → `dwh` (`dw_exposure`, `dw_collateral_alloc`, `mart_sa_exposure`) → `sa_engine.calc_sa_exposure` → `reporting_db.rpt.c0700_facts` = 1,240.5 for Corporates r0010 c0200; 9 hops; intragroup exclusion and FX as on POC screen 3.
- **Superset** (pip in WSL venv, SQLite metadata, port 8088): DB connection to `reporting_db`; datasets + table charts "COREP C90 Report" and "C 07.00 Corporates".
- **Report files**: `sandbox/reports/corep_c90_2026-06-30.pdf` (same layout as the user's PDF, entity shown as a placeholder) and `corep_2026-06-30_v1.xbrl` (C 07.00 facts).
- Out of the box the tracer only knows the report source credentials; `loans_db` (and one other) must be entered when asked, to demo the pause/resume step.

## Code layout
- `src/lineage_tracer/`: `report_reader.py` (PDF tables via pymupdf word positions; XBRL facts; CSV/XLSX), `connectors/{superset,postgres,sqlite}.py`, `sql_lineage.py`, `tracer.py` (orchestrator + persisted state), `reconcile.py`, `vault.py` (Fernet-encrypted creds; key from env; never returned by API; audited), `evidence.py` (reuse pack builder)
- `src/lineage_api/app.py`: tracer routes (below)
- `sandbox/`: setup scripts (SQL, SQLite, Superset bootstrap, ETL run, report generators), one entrypoint `sandbox/setup.ps1`
- `web/`: replace the screens with the 3 Tracer screens (keep shell, tokens, React Flow, formatters); old screens removed

## API (`/api/tracer`)
- `POST /reports` (multipart) → `{report_id, meta:{title, entity, ref_date, version, regulator?}, tables:[{id, title, columns, rows:[{key, cells}]}]}`
- `POST /traces` `{report_id, data_point:{table_id,row,column}, source:{type:"superset"|"postgresql"|"sqlite", url|host, database?, user, password, object?}}` → `{trace_id}` (runs in background)
- `GET /traces/{id}` → `{status: running|connection_required|complete|failed, header, stats:{systems_connected, sor_reached, sor_known, branches_outstanding}, steps:[{n, system, attribute_held_in, sourced_from[], consumed_by[], status}], pending?:{system, host_hint, database_hint, phase, message}}`
- `POST /traces/{id}/connections` `{system, type, host, database, user, password}` → resumes
- `GET /traces/{id}/lineage` → `{lanes, nodes, edges:[{hop, status}], hops:[{n, from, to, status, attribute_held_in, sourced_from, transformation, consumed_by, evidence:{code, version, log, reconciliation}}], summary}`
- `POST /traces/{id}/evidence-pack` → reuse existing pack builder (PDF/DOCX)
- Forward lineage (POC tab): same scanners inverted (who reads this table/column) — Phase 2.

## Guard-rails
Read-only users only; every scanner query is catalog/SELECT in a read-only transaction with statement_timeout; credentials encrypted at rest, masked in logs and audit; every connection and trace action audited (existing hash-chained log).

## Execution (Opus plans/reviews, Sonnet codes)
1. **SB agent** — sandbox estate + Superset + report files (scripted, idempotent, all on D:).
2. **TR agent** — tracer engine + API + tests (unit tests on fixtures, then end-to-end against the sandbox once SB lands).
3. **FE agent** — 3 Tracer screens against this API (fixtures first, then live).
Run 1–3 in parallel; Opus reviews, then end-to-end: upload C90 PDF → select FX/DELTA 3867.06 → Superset → … → pause at a missing connection → enter creds → complete → evidence pack. Same for C 07.00 via XBRL + direct reporting DB.

## Verification
- C90: every row of the uploaded PDF traced; FX·DELTA reaches `trading_db.trade_sensitivity` + SQLite FX rates; hops reconcile (Proven) except the SQLite hop (Code-derived via OpenLineage).
- C 07.00: 9 hops, 3 systems of record, 7 proven / 2 code-derived as POC screen 3.
- Pause/resume works; wrong password → clear error, trace stays paused.
- Scanner never writes (test: `lineage_ro` has no write grants; queries run in read-only txns).
- Existing tests still pass.
