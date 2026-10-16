# Real-world ETL pipelines (spec v1) — replaces stored-procedure loads in the demo

Goal: the tracer must discover lineage the way OpenMetadata/DataHub do when ETL is NOT in stored procedures:
query history (+ server log) for SQL pushed to the DB, and pipeline-tool metadata (Informatica mapping XML, OpenLineage from Spark) when the tool moves data itself. All databases stay PostgreSQL. C 07.00 keeps its stored procedures as the "stored procedure" example.

## 1. Report ↔ pipeline
| Report | DB / port | Pipeline | Lineage source |
|---|---|---|---|
| **LCR Liquidity Coverage** (new) | new db `lcr_mart` on 5432 (schemas raw, stg, core, rpt) | `sandbox/pipelines/lcr/run_lcr.sh` → `psql -v ON_ERROR_STOP=1 -f NN_*.sql` (set-based INSERT…SELECT, no procedures) | `pg_stat_statements` + Postgres server csvlog (`log_statement='mod'`, `log_line_prefix` with time, user, db, application_name='lcr_shell'); SQL files matched as code evidence |
| **COREP C90** | existing 5432 sandbox DBs (trading_db → staging → dwh → frtb_engine → reporting_db) | `sandbox/pipelines/informatica/` — one PowerCenter-format mapping XML per load (SOURCE/TARGET/TRANSFORMATION incl. Expression + Aggregator, CONNECTORs, expressions as in real exports) + `pmrun.py` executor that reads source rows (SELECT), evaluates the mapping's expressions in Python, writes target rows with parameterised INSERT VALUES / COPY (application_name='pmdtm'). Drops the C90 procedures and the C90 foreign tables. | Mapping XML (built-in Informatica parser) — the query log only shows unlinked reads/writes |
| **EFR Credit Risk** | `fin_lake` on 5433 | `sandbox/pipelines/spark/efr_job.py` PySpark (JDBC read raw → stg → core → rpt, transforms in DataFrame API/Spark SQL), OpenLineage Spark listener with **file transport** → events JSON → ingested into the `lineage` DB via the existing OpenLineage ingest. Drops the fin_lake `etl.sp_*` procedures. | OpenLineage events (inputs/outputs + columnLineage facet) + PySpark source file as code evidence |

Each report: Superset chart + uploadable PDF in `sandbox/reports/` + `sandbox/expected/<report>.json` (expected hops, column edges, pipeline type). Report values must reproduce exactly from source data. Keep the EFR demo value ENT-UK · Corporates · exposure_ead = 1,277.32 and C90 FX·DELTA 3,867.06 unchanged.

## 2. LCR model (Basel III LCR, simplified, 30-Jun-2026, USD m)
raw: `deposit_account(account_id, entity_code, cpty_type, product, ccy, balance, is_operational, insured)`, `security_holding(isin, entity_code, asset_class, ccy, market_value, is_encumbered)`, `cashflow(entity_code, flow_type, ccy, amount, maturity_date)`, `fx_rate(ccy, rate_date, rate_to_usd)`, `lcr_param(item_code, factor)` (run-off rates / haircuts).
stg → core: `fact_hqla(entity, level 1/2A/2B, mv_usd, haircut, weighted_usd)`, `fact_outflow(entity, category, balance_usd, runoff_rate, outflow_usd)`, `fact_inflow(...)` with 75% inflow cap.
rpt: `rpt.v_lcr_summary(entity, hqla_usd, outflows_usd, inflows_usd, net_outflows_usd, lcr_pct)` + GROUP total row; LCR = HQLA / (outflows − min(inflows, 0.75 × outflows)) × 100. Demo data point: ENT-UK · lcr_pct.

## 3. Tracer capabilities to add (generic, not demo-specific)
1. **Query-history harvester**: `POST /api/tracer/harvest` (+ optional schedule) copies new `pg_stat_statements` rows per DB into a `query_history` table (first_seen, last_seen, calls, dbid, userid, query) so lineage survives eviction/reset; tracer uses harvested history.
2. **Server-log reader**: parse Postgres csvlog (path configurable; read via `pg_read_file` when permitted or a mounted path) for statements with literals, timestamp, user, application_name → evidence "Log: 30-Jun 23:42:07 · lcr_shell · etl_owner · INSERT INTO …" and reconciliation with literal values.
3. **Code repository scan**: configured code roots (e.g. `sandbox/pipelines/`) → index `.sql`/`.sh`/`.py`/`.xml`; match executed statements to files by normalised fingerprint → evidence "Code: pipelines/lcr/03_core.sql lines 1–28".
4. **Informatica mappings**: ingest mapping XML (existing parser) as pipeline jobs with column lineage + expressions; tracer looks them up when a table has no in-DB writer.
5. **OpenLineage jobs** (Spark): use columnLineage facet (incl. transformation type/description) for column edges; job's source file as code evidence.
6. **Reconciliation for external pipelines**: logic can't be re-executed → reconcile by totals/row counts where the column edge is identity or aggregation-preserving (SUM, pass-through) → proven; otherwise code_derived with reason "pipeline logic not re-executable".
7. Evidence shows **pipeline type** (`stored_procedure | sql_script | informatica | spark | view | query_log`) per hop.
