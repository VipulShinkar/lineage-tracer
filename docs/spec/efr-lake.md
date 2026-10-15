# EFR financial data lake + OpenMetadata-style column lineage (spec v1)

EFR = Enterprise Financial Risk report, produced to meet BCBS 239 (risk data aggregation & reporting: accuracy, completeness, reconciliation, lineage). Group-level credit risk summary, reference date 2026-06-30. OLTP → raw ingestion is OUT of scope for now: `raw` tables are the starting point (systems of record for the trace).

## 1. Instance
- New PostgreSQL 18 cluster `finlake` on **port 5433** in WSL distro `Ubuntu-AGE` (`pg_createcluster 18 finlake --port 5433`), data on the D:-backed vhdx. Own config: `listen_addresses='*'`, `shared_preload_libraries='pg_stat_statements'`, `pg_stat_statements.track='all'`, scram auth for 0.0.0.0/0. Systemd-enabled.
- Database **`fin_lake`**; schemas `raw`, `stg`, `core`, `rpt`, `etl` (procedures).
- Roles: `etl_owner`/`etl_owner` (owns + runs ETL), `lineage_ro`/`lineage_ro` (pg_read_all_data, pg_read_all_stats, no writes). Same names/passwords as the 5432 cluster on purpose (the tracer's same-host credential reuse is keyed by host — see §4).

## 2. Model (columns are the contract; add audit columns `_batch_id`, `_loaded_at` to raw)
**raw** (source-shaped, text-ish types where realistic):
- `raw.entity(entity_code, entity_name, country, consolidation_group)` — 3 entities: ENT-UK, ENT-IN, ENT-SG; group GROUP-01
- `raw.counterparty(cpty_id, cpty_name, country, sector_code, is_intragroup)` — sector_code: SOV, BNK, CORP, RET
- `raw.rating(cpty_id, rating_grade, rating_date, agency)`
- `raw.loan_contract(contract_id, entity_code, cpty_id, product_code, ccy, principal, undrawn_limit, accrued_int, impairment, start_date, maturity_date)`
- `raw.collateral(collateral_id, contract_id, collateral_type, ccy, market_value)`
- `raw.credit_limit(entity_code, sector_code, limit_amount, ccy)`
- `raw.fx_rate(ccy, rate_date, rate_to_usd)`
- `raw.gl_balance(entity_code, account_code, ccy, balance, as_of)` (for a completeness check view)
**stg** (typed, cleaned, deduped; intragroup flagged): `stg.entity`, `stg.counterparty`, `stg.rating`, `stg.loan` (drawn_amt, undrawn_amt in txn ccy), `stg.collateral`, `stg.credit_limit`, `stg.fx_rate`
**core** (star):
- `dim_date`, `dim_entity`, `dim_counterparty` (+ portfolio: Sovereigns / Banks / Corporates / Retail), `dim_rating` (rating_grade → pd, lgd band), `dim_product` (product_code → ccf, risk_weight_base)
- `fact_exposure(as_of, entity_key, cpty_key, product_key, rating_key, drawn_usd, undrawn_usd, ccf, ead_usd, risk_weight, rwa_usd, pd, lgd, el_usd, collateral_usd)` — EAD = drawn + CCF × undrawn (USD via stg.fx_rate); RWA = EAD × risk_weight; EL = PD × LGD × EAD; intragroup excluded
- `fact_limit(as_of, entity_key, portfolio, limit_usd)`
**rpt**:
- `rpt.efr_credit_risk_summary` (table, loaded by procedure from core) and view **`rpt.v_efr_credit_risk_summary`** adding the GROUP / ALL total row and `utilisation_pct = exposure_ead / limit * 100`.
- Columns exactly: `entity, risk_type, portfolio, exposure_ead, rwa, expected_loss, limit_amount, utilisation_pct` (USD m, 2 dp; risk_type = 'CREDIT').
Loads: PL/pgSQL procedures `etl.sp_load_stg_*`, `etl.sp_load_core_*`, `etl.sp_load_rpt_efr` with readable multi-line `INSERT INTO … SELECT …`; run once after `pg_stat_statements_reset()`. Data: ~1,500 loans, ~400 counterparties, deterministic seed; all hops must reconcile (proven) except make ONE hop code-derived by design (e.g. `stg.collateral` reloaded after the run) and document it.

## 3. Superset + report file
- Superset DB connection "fin_lake" (`postgresql+psycopg2://lineage_ro:lineage_ro@127.0.0.1:5433/fin_lake`), virtual dataset `SELECT … FROM rpt.v_efr_credit_risk_summary`, table chart **"EFR Credit Risk Summary"**.
- `sandbox/reports/efr_credit_risk_2026-06-30.pdf`: same style as the C90 PDF — header lines "EFR Credit Risk Summary;", "[LEGAL ENTITY] Group,", "Date : 30 Jun 2026", "Prepared under : BCBS 239 risk data aggregation", then the table (generated from the view).
- `sandbox/expected/efr_ent_uk_corporates_ead.json`: expected hops/column edges for the demo data point (ENT-UK · CREDIT · Corporates · exposure_ead).

## 4. Tracer changes (backend)
- Works within one database across schemas (raw → stg → core → rpt are all in `fin_lake`), and against port 5433. Node ids stay `system.schema.table` with system = `fin_lake`.
- Same-host credential reuse must key on host **and try other ports' creds** too (5432 creds → 5433), audited as today.
- `GET /traces/{id}/lineage` additions (keep all existing fields):
```ts
nodes[]: { …existing, service: "postgresql"|"superset"|"sqlite"; database?: string; schema?: string; name: string /* table/view/chart */;
           entity_type: "table" | "view" | "chart" | "file";
           columns: { name: string; data_type?: string; in_path: boolean }[] /* all catalog columns; in_path = part of the traced lineage */ }
column_edges: { from_node: string; from_column: string; to_node: string; to_column: string; hop: number;
                transformation?: string /* e.g. "drawn_usd + ccf * undrawn_usd", "SUM", "pass-through" */ }[]
```
- Column edges come from the sqlglot column lineage already computed per statement (not only the traced column: include every target column of the statement that feeds the traced path, at least the path itself).

## 5. Lineage UI (OpenMetadata style) — replaces screen 3 graph
- No lane headers, no "system of record" tiles. Left→right auto layout (ELK layered).
- Table node card: service icon (Postgres elephant-like glyph / Superset / SQLite as simple SVG), `database.schema` small + **table name** bold, entity-type tag (Table/View/Chart). Collapsed by default to the in-path columns; "+N more columns" expands to all columns. Root (report/chart) node highlighted.
- Column-level edges: from column row handle to column row handle. Table-level edge (thick, neutral) when collapsed. Click a column → highlight its full upstream and downstream column path, dim others. Click an edge → side panel: hop n, transformation, status badge (Proven / Code-derived / Unresolved as small coloured badge), evidence (code, SQL toggle, log, reconciliation). Click a node → panel: columns with types, which procedure/view writes it.
- Controls: zoom/fit, "Expand all / Collapse all", toggle "Column lineage" on/off, upstream/downstream depth not needed for POC.
- Keep header (title, summary line, New trace, Export evidence pack).
