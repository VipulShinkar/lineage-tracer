# Lineage Tracer sandbox estate

A small, fully scripted regulatory data estate (Postgres 18 in WSL `Ubuntu-AGE`, a SQLite file, Apache Superset) that the Lineage Tracer is tested against. Two report pipelines: **C90** (FRTB sensitivities, the user's PDF) and **C 07.00** (credit risk SA, POC screens).

## Demo reports and pipelines

| Report | Pipeline type | Upload file (`sandbox/reports/`) | Superset chart | Expected file (`sandbox/expected/`) |
|---|---|---|---|---|
| COREP C 07.00 Corporates (r0010 c0200 = 1,240.5) | PL/pgSQL stored procedures + postgres_fdw (the stored-procedure example) | `corep_2026-06-30_v1.xbrl` | "C 07.00 Corporates" | `c0700_r0010_c0200.json` |
| COREP C90 FRTB (FX/DELTA 3,867.06) | Informatica PowerCenter-style mappings (`pipelines/informatica`) | `corep_c90_2026-06-30.pdf` | "COREP C90 Report" | `c90_fx_delta.json` |
| EFR credit risk (ENT-UK Corporates EAD 1,277.32) | PySpark + OpenLineage (`pipelines/spark`, db `fin_lake` :5433) | `efr_credit_risk_2026-06-30.pdf` | "EFR Credit Risk Summary" | `efr_ent_uk_corporates_ead.json` |
| LCR (ENT-UK lcr_pct 150.00) | Shell scripts running psql (`pipelines/lcr`, db `lcr_mart`) | `lcr_liquidity_2026-06-30.pdf` | "LCR Liquidity Coverage" | `lcr_ent_uk_lcr_pct.json` |

One-command rebuild of all four (about 10-15 min; `-SkipSuperset` to skip Superset), then verify:

```powershell
powershell -File sandbox/setup.ps1
.\.venv\Scripts\python sandboxerify.py   # also runs the 3 pipelines' verify.py
```

Note: `build.py` / `finlake/build.py` still create the old C90 and etl procedures; `setup.ps1` then runs the Informatica and Spark setups, which drop them. Only C 07.00 keeps procedures + foreign tables.

## Rebuild

```powershell
powershell -File sandbox/setup.ps1            # everything, from scratch, idempotent (about 2 min once Superset is installed; the first run installs it, ~10 min)
powershell -File sandbox/setup.ps1 -SkipSuperset
.\.venv\Scripts\python sandbox\verify.py       # checks as lineage_ro, recomputes every hop
```

`setup.ps1`: starts the DB (`scripts/db.ps1`) -> `wsl/configure_pg.sh` (adds `pg_stat_statements` to `shared_preload_libraries`, `track=all`, restarts only if changed) -> `build.py` (drops/recreates ONLY the 8 sandbox DBs, DDL, seed, `pg_stat_statements_reset()`, ETL once as `etl_owner`, late collateral reload) -> `verify.py` -> `wsl/install_superset.sh` -> `superset/bootstrap.py` -> `reports/make_reports.py`. Existing `lineage` / `lineage_test` DBs are never touched (the OpenLineage event is the only write to `lineage`).

## Systems

All Postgres systems: host `127.0.0.1`, port `5432` (never `localhost`).

| System | Type | Location | Role | Credentials |
|---|---|---|---|---|
| `loans_db` | PostgreSQL | db `loans_db`, `los.facility` | system of record, facilities | **`loans_ro` / `loans_ro`** (own login; `lineage_ro` cannot connect) |
| `collateral_db` | PostgreSQL | db `collateral_db`, `col.collateral` | system of record, collateral (valued in EUR) | `lineage_ro` / `lineage_ro` |
| `trading_db` | PostgreSQL | db `trading_db`, `trd.trade_sensitivity` | system of record, FRTB sensitivities (native ccy) | `lineage_ro` / `lineage_ro` |
| `market_data` | SQLite | `sandbox/data/market_data.db`, table `fx_rates` | system of record, FX feed (3 dates x 5 ccy) | file |
| `staging` | PostgreSQL | db `staging`, `public.stg_facilities / stg_collateral / stg_sensitivity / ref_fx_rates` | landing; foreign tables to the 3 PG sources; FX via `etl/load_fx.py` | `lineage_ro` |
| `dwh` | PostgreSQL | db `dwh`, `dw_exposure`, `dw_collateral_alloc`, `mart_sa_exposure`, `dw_sensitivity_usd` | warehouse + mart; foreign tables to staging | `lineage_ro` |
| `sa_engine` | PostgreSQL | db `sa_engine`, `calc_sa_exposure` | SA exposure value (CCF + CRM) | `lineage_ro` |
| `frtb_engine` | PostgreSQL | db `frtb_engine`, `calc_sbm_charge`, `ref_risk_weight` | SBM charge = sum(USD sensitivity x risk weight) | `lineage_ro` |
| `reporting_db` | PostgreSQL | db `reporting_db`, `rpt.c0700_facts`, `rpt.c90_facts`, view `rpt.v_corep_c90` | reporting layer read by Superset | `lineage_ro` |
| Superset | Apache Superset | WSL `/opt/superset`, systemd unit `superset`, `http://127.0.0.1:8088` | report source system | `admin` / `admin` |

Roles: `loans_ro` (CONNECT on `loans_db` only, USAGE + SELECT on schema `los`; `lineage_ro` and PUBLIC have CONNECT revoked there; staging's `lineage_ro` foreign-server mapping for loans maps to remote `loans_ro`), `lineage_ro` (LOGIN, `pg_read_all_data`, `pg_read_all_stats`, CONNECT on all sandbox DBs, no writes; also has `postgres_fdw` user mappings so foreign tables are readable by it), `etl_owner` / `etl_owner` (owns all sandbox DBs; runs the ETL). Admin: `lineage` / `lineage` (superuser, build only).

ETL mechanics: data crosses DBs through **postgres_fdw** (`pg_foreign_server.srvoptions` has host/dbname; `pg_foreign_table` has schema/table); loads inside a DB are **PL/pgSQL procedures** in schema `etl` (`INSERT INTO ... SELECT`, multi-line). `pg_stat_statements` was reset just before the ETL, so it holds the real INSERT statements (nested statements are tracked). Note: AGE's preload hook breaks `TRUNCATE` in non-AGE DBs, so procedures use `DELETE FROM`.

## Superset objects (created by `superset/bootstrap.py`)

- Database `reporting_db` (`postgresql+psycopg2://lineage_ro:lineage_ro@127.0.0.1:5432/reporting_db`)
- Virtual dataset `corep_c90_report` = `SELECT ... FROM rpt.v_corep_c90`; physical dataset `rpt.c0700_facts`
- Table charts **"COREP C90 Report"** and **"C 07.00 Corporates"** (filter `sheet = 'Corporates'`)

## Report files (`sandbox/reports/`)

- `corep_c90_2026-06-30.pdf` - same layout as the user's report, entity `[LEGAL ENTITY]`
- `corep_2026-06-30_v1.xbrl` - simplified XBRL instance, C 07.00 Corporates, 12 facts (3 rows x 4 cols), contexts with period 2026-06-30 and explicit dimensions Template/Sheet/Row/Column
- Values are read from `reporting_db`, regenerated by `setup.ps1`.

## Reported values (reproduced exactly)

C90 (USD): COM/DELTA 3916.49, CSR_NS/DELTA 1176.02, EQ/CURVATURE 0.45, EQ/DELTA 34.01, EQ/VEGA 2.26, FX/CURVATURE 51.45, FX/DELTA 3867.06, FX/VEGA 257.27, GIRR/DELTA 321.95, ALL/ALL 9626.96 (~260 trades, 5 currencies, one adjusted trade per bucket).

C 07.00 Corporates (EUR m), cols 0010 / 0040 / 0200 / 0220: r0010 1265.4 / 1243.8 / **1240.5** / 1118.9; r0040 1061.9 / 1042.0 / 1041.4 / 962.0; r0050 203.5 / 201.8 / 199.1 / 156.9. (1,116 facilities; the 251 intragroup ones are excluded, leaving 865 in `dw_exposure`.) Column meaning (simplified): 0010 original exposure, 0040 net of value adjustments, 0200 exposure value after CCF and CRM, 0220 of which RATED.

## What the tracer should discover

Machine-readable: `sandbox/expected/c90_fx_delta.json`, `sandbox/expected/c0700_r0010_c0200.json`.

**C90, FX / DELTA 3867.06** - Superset chart -> dataset `rpt.v_corep_c90` -> `reporting_db` ->
`rpt.c90_facts` (view) -> `frtb_engine.calc_sbm_charge` (proven) -> `dwh.dw_sensitivity_usd` (proven) -> `staging.stg_sensitivity` (proven) + `staging.ref_fx_rates` (proven) -> `trading_db.trd.trade_sensitivity` (SoR, proven) and SQLite `fx_rates` (SoR; **code-derived**: only OpenLineage evidence). Plus the static parameter table `frtb_engine.ref_risk_weight` (SoR branch). 6 proven, 1 code-derived.

**C 07.00, Corporates r0010 c0200 = 1,240.5** - `rpt.c0700_facts` <- `sa_engine.calc_sa_exposure` (hop 9) <- `dwh.mart_sa_exposure` (8) and `dwh.dw_collateral_alloc` (7, **code-derived**) ; mart <- `dw_exposure` (6) <- `stg_facilities` (3) + `ref_fx_rates` (4); `dw_collateral_alloc` <- `stg_collateral` (5, **code-derived**); `stg_facilities` <- `loans_db` (1); `stg_collateral` <- `collateral_db` (2); `ref_fx_rates` <- SQLite (10, **code-derived**, OpenLineage). 10 hops: 7 proven, 3 code-derived, 3 systems of record. (POC screen 3 shows 9 hops / 2 code-derived because it stops at the FX feed; here the feed itself is a SQLite file.)

Why hops 5 and 7 are code-derived: after the ETL, `col.collateral` market values were revalued x1.5 and `stg_collateral` reloaded (so hop 2 still reconciles), while `dw_collateral_alloc` was left stale-and-patched (x0.5, by an admin statement hidden from the query log). Recomputing the alloc from current staging, or the SA exposure from the current alloc, no longer reproduces the stored values. Caveat for the reconciler: hop 8 (mart -> calc) reconciles on the `orig_*` columns; for the CRM-dependent columns hold the alloc input fixed.

## Demo script

The user knows only Superset (`admin`/`admin`, http://127.0.0.1:8088) and `reporting_db` (`lineage_ro`/`lineage_ro`).

1. Upload `corep_c90_2026-06-30.pdf`, select FX / DELTA 3867.06, source = Superset (chart "COREP C90 Report"). Exactly **one** credential pause: `reporting_db` -> enter `lineage_ro` / `lineage_ro` (127.0.0.1:5432); the rest of the chain reuses it. FX ends at SQLite via the OpenLineage event.
2. Upload `corep_2026-06-30_v1.xbrl`, select Corporates r0010 c0200, source = PostgreSQL `127.0.0.1:5432` / `reporting_db` (`lineage_ro`/`lineage_ro`). Exactly **one** credential pause: `loans_db` -> enter `loans_ro` / `loans_ro` (every other system accepts the stored `lineage_ro` credentials).
3. Wrong password -> clear error and the trace stays paused.

## EFR financial lake (second cluster, port 5433)

Spec: `docs/spec/efr-lake.md`. A separate Postgres 18 cluster `finlake` (WSL, D:-backed, `shared_buffers=128MB`, `max_connections=30`, systemd `postgresql@18-finlake`), database **`fin_lake`**, schemas `raw` -> `stg` -> `core` (star) -> `rpt`, procedures in `etl`. Roles `etl_owner`/`etl_owner` (owns + runs ETL) and `lineage_ro`/`lineage_ro` (read-only), host `127.0.0.1:5433`.

- Rebuild: part of `sandbox/setup.ps1`, or alone `powershell -File sandbox/finlake/setup.ps1` (`-SkipSuperset`). `sandbox/verify.py` also runs `finlake/verify.py`.
- Data: 3 entities, 400 counterparties (+10 stale duplicates), 1,500 loans, 899 collaterals, 12 limits; deterministic seed. `pg_stat_statements` holds the real INSERTs from one ETL run.
- Report: Superset database `fin_lake`, virtual dataset over `rpt.v_efr_credit_risk_summary`, table chart **"EFR Credit Risk Summary"**; PDF `sandbox/reports/efr_credit_risk_2026-06-30.pdf`.
- Demo data point: **ENT-UK . CREDIT . Corporates . exposure_ead = 1,277.32 (USD m)** (rwa 1,095.60, EL 34.10, limit 1,840.85, utilisation 69.39%). Group total EAD 5,822.03.
- Expected lineage: `sandbox/expected/efr_ent_uk_corporates_ead.json` (16 table hops + column edges). Exactly one code-derived hop: `raw.fx_rate -> stg.fx_rate` (GBP/INR 30-Jun rates restated in raw after the run; stg not reloaded). All others reconcile.

## LCR liquidity coverage (SQL-script pipeline, db `lcr_mart` on 5432)

Spec: `docs/spec/pipelines.md`. Schemas `raw` -> `stg` -> `core` -> `rpt`, **no stored procedures**: `sandbox/pipelines/lcr/run_lcr.sh` runs the numbered files (`10_stg_*`, `20_core_*`, `30_rpt_*`, `31_rpt_v_lcr_summary.sql`) with `PGAPPNAME=lcr_shell psql -v ON_ERROR_STOP=1 -h 127.0.0.1 -U etl_owner -d lcr_mart -f ...`.

- Rebuild: `powershell -File sandbox/pipelines/lcr/setup.ps1 [-SkipSuperset]` (csvlog config -> drop/create db -> seed -> pipeline -> Superset -> PDF -> `verify.py`).
- Data: 3 entities, 2,000 deposits, 300 securities, 120 cash flows, FX 30-Jun-2026. Superset chart **"LCR Liquidity Coverage"** (dataset over `rpt.v_lcr_summary`), PDF `sandbox/reports/lcr_liquidity_2026-06-30.pdf`.
- Demo data point: **ENT-UK . lcr_pct = 150.00** (HQLA 414.60, outflows 405.51, inflows 129.11, net 276.40 USD m); ENT-IN 125.00, ENT-SG 175.00, GROUP 151.45.
- Evidence: `pg_stat_statements` (db `lcr_mart`) and the server csvlog `/var/lib/postgresql/18/main/log/postgresql-YYYY-MM-DD_HHMMSS.csv` (`logging_collector=on`, `log_destination=csvlog`, `log_statement=mod`, daily/20MB rotation; `conf.d/lcr_log.conf` applied by `configure_log.sh`, restart only on change). `lineage_ro` has `pg_read_server_files` + `pg_monitor` and EXECUTE on `pg_read_file` in `lcr_mart`: `SELECT name FROM pg_ls_logdir()`, then `SELECT pg_read_file('log/<name>')`; csvlog column 23 is `application_name` (`lcr_shell`), column 14 `message` is `statement: INSERT INTO ...`.
- Expected lineage: `sandbox/expected/lcr_ent_uk_lcr_pct.json` (18 table hops, all proven, pipeline type `sql_script`, code file + line ranges).

## C90 as an Informatica PowerCenter pipeline (`sandbox/pipelines/informatica/`)

The four C90 loads (trade_sensitivity -> stg_sensitivity -> dw_sensitivity_usd -> calc_sbm_charge -> rpt.c90_facts) are no longer PL/pgSQL procedures over postgres_fdw. Each is a PowerCenter-format export `m_C90_*.xml` (POWERMART/REPOSITORY/FOLDER/SOURCE/TARGET/MAPPING with Source Qualifier, Lookup Procedure, Filter, Expression, Aggregator, CONNECTORs, plus SESSION/WORKFLOW). `connections.xml` maps the connection names used as `DBDNAME` (`trading_db`, `staging`, `dwh`, `frtb_engine`, `reporting_db`) to host 127.0.0.1 / port 5432 / db. `pmrun.py <mapping.xml>` acts like the DTM in normal mode: plain SELECT reads, Python evaluation of expressions/lookups/aggregation, `DELETE` + `INSERT ... VALUES` (executemany) writes, `application_name='pmdtm'` - so the query log shows only unlinked reads and writes; lineage must come from the XML. The FX feed (SQLite -> `staging.ref_fx_rates`, OpenLineage) and `frtb_engine.ref_risk_weight` are unchanged. C 07.00 is untouched.

```powershell
powershell -File sandbox/pipelines/informatica/setup.ps1   # idempotent: drop C90 procs/foreign tables, run 4 mappings, verify (needs build.py to have run)
powershell -File sandbox/pipelines/informatica/run_c90.ps1 # just the mappings (or run_c90.sh)
```

`gen_mappings.py` regenerates the XML. Reported values are identical (FX/DELTA 3,867.06, ALL 9,626.96). Expected hops with mapping files, transformations and column edges with expressions: `sandbox/expected/c90_fx_delta.json`. Note: `build.py` still creates the old C90 procedures/foreign tables, so run `pipelines/informatica/setup.ps1` after it (and `sandbox/verify.py` C90 fdw checks no longer apply).

### EFR lake ETL as PySpark + OpenLineage (`sandbox/pipelines/spark/`)

Replaces the fin_lake `etl.sp_load_*` procedures (dropped). `efr_job.py` reads raw/stg/core over JDBC (`ApplicationName=spark_efr`), applies the same business logic in Spark SQL and writes each of the 15 target tables back (overwrite + truncate, DDL/comments kept) - one Spark write = one OpenLineage run. Spark 3.5 + JDK 17 + OpenLineage jar live **inside WSL** (`/opt/spark-venv`, `/opt/spark-jars`; ~0.5 GB on D:), run as `local[2]`, driver 1 GB.

- Run: `powershell -File sandbox/pipelines/spark/setup.ps1` (installs if missing, resets raw FX, runs job, drops procedures, restates GBP/INR 30-Jun FX x1.015 in raw without reloading stg, ingests events). Check: `.venv\Scripts\python sandbox/pipelines/spark/verify.py`. Needs fin_lake built first.
- Events: `sandbox/openlineage/spark/efr_events.ndjson` (file transport, namespace `efr_spark`, job `efr_credit_risk.execute_save_into_data_source_command.<schema>_<table>`). Datasets: namespace `postgres://127.0.0.1:5433`, name `fin_lake.<schema>.<table>`. COMPLETE events carry `outputs[].facets.columnLineage`; `ingest_events.py` feeds them to `lineage_store.ingest_ol`.
- Expected lineage: `sandbox/expected/efr_ent_uk_corporates_ead.json` (pipeline `spark`, code evidence with line ranges in `efr_job.py`). Demo value unchanged: ENT-UK . Corporates . exposure_ead = 1,277.32.
- Note: rebuilding with `sandbox/finlake/build.py` recreates the procedures; rerun the Spark setup afterwards.
