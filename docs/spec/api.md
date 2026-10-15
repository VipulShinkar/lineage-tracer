# Lineage Explorer — API contract (v1)

Shared contract between backend (`src/lineage_api`) and frontend (`web/`). Both sides build to this file; change it first, then code.
Source of truth for screens and numbers: `figma/Reg Lineage – Journey & Screens.pdf` (page N = screen, see table at end).

## Conventions
- Base path `/api`. JSON. Amounts are numbers in **EUR millions**, one decimal unless stated. Dates `YYYY-MM-DD`, timestamps ISO-8601.
- **Submission** selects the point in time: query param `sub` (e.g. `sub=2026-06-30.v1`). Default = latest submitted. Graph edges/rule versions are filtered to `valid_from <= ref_date <= valid_to`.
- **Role**: request header `X-Role: analyst | supervisor | data_owner | head_of_reg` (default `analyst`). `X-Actor: <display name>` optional (default `[Analyst B]`). Server enforces masking and read-only; the UI only mirrors it.
  - `supervisor` = read-only, masked, cannot reveal. `analyst` = masked by default, may reveal one identifier with a reason (audited).
- **IDs** (stable `uid`, URL-safe, used in paths as-is):
  - cell: `C07.00:Corporates:r0010:c0200` · template: `C07.00` · submission: `2026-06-30.v1`
  - node uids: `system:loan_origination`, `dataset:stg_credit_facilities`, `field:dw_exposure.drawn_amount_eur`, `job:hop3`, `rule:T4`, `mapping:product_to_class`, `control:H3_gl_recon`, `adj:ADJ-2026-Q2-014`, `gap:haircut_table`
- Coverage status enum: `complete | partial | gap | not_in_scope`. Control status: `pass | fail | waived`.
- Errors: `{ "detail": "message" }` with 4xx/5xx. 403 when role not allowed.
- Every response for a cell includes `cell_header` so tabs can render the header strip without another call:
  ```ts
  type CellHeader = { cell_id: string; template: string; template_name: string; sheet: string;
    row: string; row_label: string; col: string; col_label: string; value: number; unit: "EUR m";
    coverage: Coverage; coverage_note: string /* "1 known gap" */ }
  ```

## Context & navigation
`GET /api/contexts` → S01 filter bar
```ts
{ report_families: ["COREP (EBA DPM)"], entities: ["[LEGAL ENTITY]"], bases: ["Solo"],
  submissions: { id: string; ref_date: string; version: string; submitted_on: string; label: string /* "v1 · submitted 11-Aug-2026" */ }[] }
```
`GET /api/templates?sub=` → S01 table + side cards
```ts
{ templates: { id: "C07.00"; code: "C 07.00"; name: string; pilot_cells: number; cells_total_in_scope: number;
    coverage: { complete: number; partial: number; gap: number; label: string }; in_scope: boolean; scope_note?: "After Day 60" }[];
  pilot_scope: { total: 10; complete: 7; partial: 2; gap: 1; description: string };
  recent_queries: { cell_id: string; label: string }[] }
```
`GET /api/templates/{template}/grid?sheet=Corporates&sub=` → S02
```ts
{ template: { id; code; name }; sheets: string[]; sheet: string;
  columns: { code: "0200"; label: "Exposure value" }[];
  rows: { code: "0010"; label: "Total exposures"; bold?: boolean;
          cells: { col: "0200"; cell_id: string; value: number; coverage: Coverage }[] }[] }
```
`GET /api/cells/{cell_id}?sub=` → S02 side panel
```ts
{ cell_header: CellHeader; dpm_id: string; hops: 7; first_hop_systems: 3; transformations: 8;
  manual_adjustments: { count: 1; total: -18.3 }; business_definition: string; gap_summary?: string }
```
`GET /api/search?q=&kind=all|system|field|rule|mapping|control|record|cell&sub=` → header search (S01) and S10
```ts
{ results: { uid: string; kind: string; name: string; subtitle: string; feeds_cells: number; verb: "Feeds" | "Guards" }[] }
```

## Reverse lineage (Stage 1)
`GET /api/cells/{cell_id}/lineage?level=system|dataset|attribute&sub=` → S03 hop graph
```ts
{ cell_header; level;
  lanes: ["FIRST HOP","STAGING","WAREHOUSE","REG DATA MART","ADJUSTMENTS","REG ENGINE","SUBMISSION"];
  nodes: { uid; kind: "source"|"reference"|"gap"|"dataset"|"field"|"manual"|"calc"|"anchor"; label: string; sublabel?: string; lane: number }[];
  edges: { src; dst; hop?: number /* 1..7 badge */; dashed?: boolean /* gap */ }[];
  summary: { hops: 7; first_hop_systems: "3 + FX reference"; transformations: 8; manual_adjustments: "1 · −18.3";
             controls: "13 pass · 1 waived"; unexplained_residual: 0.0 };
  known_gaps: { uid; title: string; description: string; owner: string; target_date: string; status: "opened" }[];
  cell_dependencies: string /* "This cell feeds C 02.00 … and C 03.00 CET1 ratio." */ }
```
`GET /api/cells/{cell_id}/hops/{n}?sub=` (n = 1..7) → S04
```ts
{ cell_header; path: { n: number; label: string; manual?: boolean }[] /* 7 chips */;
  hop: { n; from: string; to: string; mechanism; frequency; cutoff; actual_run: string; run_id: string; rerun: boolean };
  records: { in: number; out: number; note: string; value_in: number; value_out: number; waterfall_step?: string };
  ownership: { data_owner; system_owner; certified: string; open_dq_issues: string };
  mappings: { source_field; target_field; what_happens: string }[];
  controls: { id; name; status: ControlStatus; detail: string }[] }
```
`GET /api/cells/{cell_id}/transformations?sub=` → S05
```ts
{ cell_header; as_of: string;
  transformations: { id: "T1"; type: "PASS-THROUGH"|"FX CONVERSION"|"SCOPE FILTER"|"MAPPING"|"MANUAL ADJUSTMENT"|"DERIVATION"|"SCALING";
    hop: string /* "Hop 1–2" */; amount: number; description: string; version: string; effective_from?: string;
    owner: string; reference: { label: string; url?: string }; manual?: boolean; adjustment_id?: string; approved_on?: string }[];
  mapping: MappingView /* the one used by T4 */;
  dependency: { text: string; formula: string } }
```
`GET /api/mappings/{mapping_uid}?version=3.2&compare=3.1&cell=` →
```ts
type MappingView = { uid; name: "product → exposure class"; version: string; effective_from: string;
  rows: { code; label; target; changed?: boolean }[]; previous_version?: string; differs_in?: number }
```
`GET /api/cells/{cell_id}/waterfall?sub=` → S06
```ts
{ cell_header;
  steps: { key; label: "Source"|"FX to EUR"|…|"Reported"; sublabel: "T2 · hop 3"; amount: number; kind: "total"|"delta"|"manual";
           link: { type: "rule"|"adjustment"|"hop"; id: string } }[];
  residual: 0.0; tolerance: 0.1; within_tolerance: true;
  adjustment: { id; amount; description; maker: string; maker_at: string; checker: string; checker_at: string;
                source: string; evidence: { label: string; url: string } };
  controls: { summary: "13 pass · 1 waived · 0 fail"; items: { hop: "H1"; name: string; status: ControlStatus }[] } }
```
Waterfall invariant (server computes, test asserts): `steps[0].amount + Σ deltas = reported`, residual = reported − that sum.

`GET /api/cells/{cell_id}/records?group_by=sector|product|source_system&compare=2026-03-31.v1&top=5&sub=` → S07
```ts
{ cell_header; contributing_records: 3418; drilldown_total: 1240.5; equals_reported: true;
  groups: { key: string; records: number; current: number; compare: number; change: number }[];
  total: { records; current; compare; change };
  top: { record_key: string; counterparty: string /* masked "CPTY-•••1107" unless revealed */; sector_product: string;
         source: string; source_key: string /* masked */; value: number }[];
  masking: { masked: boolean; can_reveal: boolean } }
```
`GET /api/records/{record_key}/trace?sub=` → S07 right card
```ts
{ record_key; title: "CPTY-•••2764 · term loan · Transport";
  steps: { hop: "H1"; label: string; sublabel: string; amount: number; ccy?: "USD"|"EUR" }[] }
```
`POST /api/records/{record_key}/reveal` body `{ reason: string }` → `{ counterparty: "CPTY-00012764", source_key: "LOS-FAC-00123458" }`. 403 for `supervisor`. Writes audit `revealed an identifier`.

`GET /api/cells/{cell_id}/regulator?sub=` → S08 (writes audit `opened regulator view`)
```ts
{ cell_header; narrative: string /* generated from stored facts, no LLM */;
  stages: { label: "Source systems"|"Prepared"|"Classified"|"Adjusted"|"Reported"; value: number; note: string; manual?: boolean }[];
  stats: { hops: 7; transformations: 8; manual_adjustments: 1; controls_passed: "13 / 14"; unexplained: 0.0; records: 3418 };
  limitations: { text: string }[];
  evidence: { next_ref: "EP-2026-Q2-0042"; linked_request: "[REF]"; sections: { key; label; default: true }[];
              formats: ["pdf","docx"]; last_pack?: { ref; created_on } } }
```
`POST /api/cells/{cell_id}/evidence-pack?sub=` body `{ sections: string[]; format: "pdf"|"docx" }`
→ `{ ref: "EP-2026-Q2-0042"; sha256: string; download_url: "/api/evidence-packs/EP-2026-Q2-0042"; created_at }`. Immutable; each call = new ref. Watermark: viewer, time, ref. Audit `generated evidence pack`.
`GET /api/evidence-packs/{ref}` → file download (`application/pdf` or docx).

## Governance
`GET /api/coverage?sub=` → S09
```ts
{ refreshed_at: string;
  kpis: { cells_complete: "7 / 10"; cells_note; hops_certified_pct: 86; hops_note: "43 of 50 hops"; unexplained_breaks: 0;
          adjustments_approved: "4 / 4"; open_gaps: 1; open_gaps_note: "target 15-Dec-2026"; evidence_packs: number };
  by_template: { template: string; name: string; cells; complete; partial; gap; status: string }[];
  certification: { owner: string; nodes: number; pct: number; status: string /* "Certified 04-Nov" | "Due 20-Nov" */ }[] }
```
`GET /api/audit?limit=50` →
```ts
{ chain_valid: boolean; retention: "7 years";
  entries: { seq; ts; actor; role; action: string; target: string; detail?: string }[] }
```
Audit log is append-only; each row stores `prev_hash` and `hash = sha256(prev_hash || canonical_json(row))`. `chain_valid` recomputes.

## Forward impact (Stage 2)
`GET /api/search?...&kind=` (above) drives S10 list. Analysis settings are client state passed to the next call.
`GET /api/elements/{uid}/impact?sub=` → S11
```ts
{ element: { uid; name: string; kind };
  stats: { templates: 3; cells: 8; entities: 1; dependency_levels: 2 };
  lanes: ["START","STAGING","WAREHOUSE","REG ENGINE","C 07.00 CELLS","DEPENDENT CELLS"];
  nodes: { uid; label; sublabel?; lane: number; kind: "start"|"hop"|"cell"|"dependent" }[];
  edges: { src; dst }[];
  impacted: { cell_id: string; label: string; ref: string /* "C 07.00 r0010 c0200" */ }[] }
```
`POST /api/elements/{uid}/what-if?sub=` body `{ haircut_pct: 15, incident_ref?: "INC-[NUMBER]", reason?: "dq_incident" }` → S12
```ts
{ rows: { cell_id; label; ref; reported: number; from_element: number; estimated: number; change: number;
          pct_of_cell: number; threshold: "within"|"near"|"above" }[];   // near = ≥ 50% of 1% threshold
  ratio: { cell_id: "C03.00:…"; label: "CET1 ratio (C 03.00)"; reported_pct: 14.82; estimated_pct: number; change_bps: number; threshold_bps: 10 };
  decision: { level: "discuss"|"none"|"resubmit"; title: string; text: string };
  cde_footprint: { field: string; cells: number; of: 10 }[];
  method_note: string }
```
Rule: `change = −from_element × haircut`; dependent cells recomputed from `DEPENDS_ON.formula` (C02 TREA = Σ RWEA changes; C03 = C01 / C02).
At 15 % this must reproduce PDF p15: +0.2, +0.2, +7.3, +1.5, +2.1, +1.6, TREA +3.3, CET1 −0.5 bps.
`POST /api/impact-report` body `{ element_uid, haircut_pct, incident_ref }` → file download (PDF). Audited.

## Ingestion
`POST /api/ingest/sql` body `{ path?: string; content?: string; file_type?: "sql"|"xml" }` → runs the built-in SQL/XML lineage parser (`lineage_parser`) and upserts Dataset/Field nodes + DERIVES edges → `{ nodes_upserted, edges_upserted }`.
`POST /api/ingest/openlineage` body = OpenLineage `RunEvent` (with `columnLineage` facet and optional custom facets `recordCounts`, `controlResult`, `manualAdjustment`) → `{ run_id, nodes_upserted, edges_upserted }`.

## Screen ↔ PDF page ↔ endpoints
| Screen | PDF page | Endpoints |
|---|---|---|
| Journey map | 1 | static |
| S01 Report browser | 4 | contexts, templates, search |
| S02 Template grid | 5 | grid, cells/{id} |
| S03 Hop graph | 6 | lineage |
| S04 Hop detail | 7 | hops/{n} |
| S05 Transformations | 8 | transformations, mappings |
| S06 Value waterfall | 9 | waterfall |
| S07 Records | 10 | records, trace, reveal |
| S08 Regulator view | 11 | regulator, evidence-pack |
| S09 Coverage | 12 | coverage, audit |
| S10 Impact search | 13 | search |
| S11 Impact graph | 14 | impact |
| S12 Sizing | 15 | what-if, impact-report |
