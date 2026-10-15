# Lineage Tracer — API contract (v1)

Base `/api/tracer`. JSON unless stated. Dates ISO (`2026-06-30`), the UI formats them. Amounts are numbers in the report's unit.
Shared by `src/lineage_tracer` + `src/lineage_api` (backend) and `web/` (frontend). Change this file first, then code.

```ts
type SystemType = "superset" | "postgresql" | "sqlite"
type HopStatus = "proven" | "code_derived" | "unresolved"
type StepStatus = "identified" | "connection_required" | "scanning" | "unresolved" | "failed"
type Lane = "system_of_record" | "staging" | "warehouse" | "data_mart" | "calc_engine" | "reporting_layer" | "report_tool"
```

## 1. Upload report — screen 1
`POST /reports` multipart `file` (PDF, XBRL/XML, CSV, XLSX) →
```ts
{ report_id: string; file_name: string;
  meta: { title: string /* "COREP C90 Report" */; return_type?: "COREP"; entity?: string; ref_date?: string;
          version?: string; delivered_to?: string; template?: string };
  tables: { id: string; title: string /* "C 07.00 · Credit risk SA · Corporates" or "C90" */;
            key_columns: string[] /* e.g. ["consolidation_group","risk_class","sensitivity_type"] or ["Row","Item"] */;
            column_labels?: Record<string,string> /* "0200" -> "Exposure value" (C 07.00 only) */;
            value_columns: string[] /* e.g. ["reported_value_usd"] or ["0010","0040","0200","0220"] */;
            unit?: string /* "USD" | "EUR m" */;
            rows: { index: number; key: Record<string,string>; values: Record<string, number | null> }[] }[] }
```
`GET /reports/{report_id}` → same.

## 2. Start trace — screen 1 → 2
`POST /traces`
```ts
{ report_id: string; data_point: { table_id: string; row: number; column: string };
  direction: "reverse";
  source: { type: SystemType; name?: string /* display, e.g. "superset" or "reporting_db" */;
            url?: string /* superset: http://127.0.0.1:8088 */; host?: string /* "127.0.0.1:5432" */;
            database?: string; path?: string /* sqlite file */; user?: string; password?: string;
            object?: string /* superset chart title or db table/view; optional — default = report title */ } }
```
→ `{ trace_id: string }` (trace runs in a background task). Credentials go to the vault; never echoed back.

## 3. Trace progress — screen 2 (poll every ~1 s)
`GET /traces/{trace_id}` →
```ts
{ trace_id; status: "running" | "connection_required" | "complete" | "failed"; error?: string;
  header: { direction: "reverse"; template?: string; label: string /* "C 07.00 · Corporates · r0010 c0200" or "C90 · GROUP-01 · FX · DELTA" */;
            value: number; unit?: string; ref_date?: string };
  stats: { systems_connected: number; sor_reached: number; sor_known: number /* reached + pending */; branches_outstanding: number };
  steps: { n: number; system: string; system_type: SystemType; attribute_held_in: string[]; sourced_from: string[];
           sourced_from_is_sor?: boolean /* "System of record" shown in green */; consumed_by: string[]; status: StepStatus }[];
  pending?: { system: string /* "loans_db" */; type: SystemType; host_hint?: string; database_hint?: string;
              phase: "connect" | "locate_attribute" | "identify_source" | "identify_consumers";
              message: string /* "stg_facilities.drawn_balance is sourced from los.facility on loans_db. Read-only connection details are required to continue." */ } }
```

## 4. Provide missing connection — screen 2
`POST /traces/{trace_id}/connections`
`{ system: string; type: SystemType; host?: string; database?: string; path?: string; user: string; password: string }`
→ 200 `{ ok: true }` (trace resumes) · 400 `{ detail: "could not connect: <reason>" }` (trace stays paused).

## 5. Lineage and evidence — screen 3
`GET /traces/{trace_id}/lineage` →
```ts
{ header; summary: { hops: number; proven: number; code_derived: number; unresolved: number; systems_of_record: number;
                     title: string /* "EUR 1,240.5m traced to 3 systems of record" */ };
  lanes: Lane[] /* left→right, only lanes in use */;
  nodes: { id: string; system: string; object: string /* "los.facility" */; lane: Lane; kind: "sor" | "intermediate" | "anchor" }[];
  edges: { from: string; to: string; hop: number; status: HopStatus }[];
  hops: { n: number; status: HopStatus; from: string; to: string; attribute_held_in: string[]; sourced_from: string[];
          transformation: string /* plain English, derived from the SQL */; consumed_by: string;
          evidence: { code?: string /* "dwh: function etl.sp_load_exposure lines 88–131" */; sql?: string;
                      version?: string /* "definition sha256 1a2b3c… · captured 2026-10-06" */;
                      log?: string /* "pg_stat_statements · 1 call · INSERT INTO dw_exposure …" | "OpenLineage run <id>" */;
                      reconciliation?: string /* "Recalculated 1,288.4 agrees to stored value" | "Not reconciled: …" */ } }[] }
```
`POST /traces/{trace_id}/evidence-pack` `{ format: "pdf" | "docx" }` → `{ ref, sha256, download_url }`; `GET /api/evidence-packs/{ref}` (existing).

## 6. Utility
`GET /traces` → recent traces `{ trace_id, label, status, created_at }[]`.
`GET /systems` → known systems from the vault `{ system, type, host, database }[]` (no secrets).

Errors: `{ detail }`, 4xx/5xx. Every connection attempt, trace start/finish and pack export is written to the audit log.

## Implementation notes (TR)
- `hops[].from/to` and `edges[].from/to` are node ids, `system.schema.table` (SQLite: `market_data.db.fx_rates`; Superset chart: `superset.<title>`).
- Foreign tables are not hops: the hop goes from the remote table to the reader, with the foreign table named in `evidence.code`.
- `tables[].column_labels` added (C 07.00 XBRL only); `default_row/default_column` not provided.
- Hop status uses the rule: a hop is proven when its own SQL applied to the stored inputs reproduces the stored output.
- Credential reuse: before pausing for a PostgreSQL system the tracer tries the vault credentials of other systems on the same host (most recent first); on success they are stored for that system, audited ("connected to X using credentials of Y") and noted in `evidence.log` of the hops read from X. A pause happens only when none works.
- Hop numbering: when a trace completes, hops are renumbered source -> report (hop 1 starts at a system of record, the last hop ends at the anchor; ordered by depth from the systems of record, ties by lane then name). `steps` keep discovery order.
- `DELETE /systems` clears all saved connections (audit "cleared saved connections") -> `{ removed: number }`. `DELETE /systems/{system}` removes one (404 if unknown) -> `{ removed: number }`.

## Lineage additions (EFR lake)
- `GET /traces/{id}/lineage`: `nodes[]` gain `service`, `database?`, `schema?`, `name`, `entity_type` (`table|view|chart`), `columns[{name,data_type?,in_path}]` (all catalog columns; Superset chart: dataset columns). `in_path` = the column is on the traced lineage (traced/filter column or an endpoint of a path column edge).
- Top-level `column_edges[{from_node,from_column,to_node,to_column,hop,transformation?}]`: for every discovered statement, every target column and the source columns feeding it (sqlglot column lineage); `transformation` is the unqualified expression (`drawn + ccf * undrawn`, `SUM(ead)`) or `pass-through`. `hop` matches `hops[].n` after renumbering.
- Works across schemas within one database (node ids stay `system.schema.table`).
- Credential reuse also tries credentials stored for other ports on the same host.
- `column_edges[].kind`: `"value"` (source column contributes to the target value expression) or `"filter"` (only used in JOIN / WHERE / GROUP BY). `transformation` is composed through CTEs and subqueries, unqualified, pure type casts dropped (`ROUND(SUM(ead_usd) / 1000000, 2)`); the SQL evidence keeps the original text.
- `hops[].on_value_path` and `nodes[].on_value_path`: on the upstream path of the reported value following `value` edges only. `default_hop`: the hop whose `to` is the anchor (the reported data point's last hop).
- `header.unit` falls back to a derived unit when the report has none (currency suffix of a source column, `/ 1000000` scaling -> `"USD m"`); `summary.title` carries it (`"USD 1,277.32m traced to 4 systems of record"`).

## Whole-report mode and business logic
- `POST /traces` gains `mode: "data_point" | "report"` (default `data_point`). In `report` mode `data_point` is `{ table_id }` only. Every numeric report column that maps to a numeric column of the source table is traced (key columns are followed as filters/dimensions). The header has `value: null`, `label: "<title> · whole report"`, `mode`; `summary.title` is `"Whole report (N value columns) traced to …"`. Reconciliation compares **column totals** (the whole reported table, with the report date filter when the table has a date column) instead of one row; the Superset hop is proven when the chart returns every reported row and the table totals agree with the report.
- Glossary (deterministic, no LLM): `nodes[].description?` and `nodes[].columns[].description?` come from `COMMENT ON TABLE/COLUMN` (PostgreSQL) or Superset chart/dataset-column descriptions (SQLite has none). `hops[].purpose?` is the writing procedure/view comment.
- `hops[].business_rules: string[]` and `column_edges[].business_rule?: string`: plain-English rules derived from the SQL AST using glossary terms where present, for example `Exposure at Default in USD = ROUND(drawn × rate, 2) + ccf × …, rounded to 2 dp`, `Converted to USD at the 30-Jun-2026 FX rate`, `Intragroup counterparties excluded`, `Sum of …, expressed in millions (÷1,000,000), rounded to 2 dp`, `Summed by entity and portfolio`, `Total row GROUP/ALL = sum of the detail rows`, `sector_code mapped by lookup: 'CORP' → 'Corporates', …`, `Looks up dim_product (matched on product_code)`, `Deduplicated: keeps the first-ranked row per key (latest delivery)`. Covers arithmetic, CASE mappings, lookups/joins, WHERE and date filters, GROUP BY, ROUND/scaling, UNION total rows, COALESCE defaults.
- `hops[].business_rules` are hop-specific: only the rules involving that hop's source table (formula on the base table, FX conversion on the rate table, "X looked up from <dim> by <key>" on each dimension, filters on the table holding the filtered column). `hops[].statement_rules: string[]` is the full statement-level list ("All rules in this load step"). Glossary terms are the leading noun phrase of the column comment (up to the closing parenthesis or ':'; at most 45 characters).
