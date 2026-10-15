# Plan — Lineage Explorer (build everything in `figma/Reg Lineage – Journey & Screens.pdf`)

## Context
The PDF specifies a regulatory lineage tool for COREP: reverse lineage from a report cell back to source systems (S01–S09) and forward impact from a source element to report cells (S10–S12), plus the data-flow/capture architecture (page 2). Goal: a **fully working** app — real Postgres, real traversal, computed waterfall, real evidence pack files, masking, audit log, what-if — seeded with example data that reproduces every number in the PDF. The built-in SQL/XML parsers serve as the design-time lineage ingester. Opus plans/reviews; Sonnet agents write the code.

Constraints from user: everything installed on **D:**; prefer embedded Postgres.

## Decisions
- **Graph DB: Apache AGE (Postgres extension)** — chosen over JanusGraph after research (30-Sep-2026):
  - ASF, Apache 2.0, actively released (v1.8.0 19-Sep-2026; 77 commits / 6+ contributors in 6 months). JanusGraph: last release Nov-2024, ~2 maintainers. Rejected also: Memgraph/ArangoDB (BSL), Neo4j (vendor, paid clustering/RBAC), NebulaGraph (vendor), Kuzu (archived).
  - openCypher for traversal + SQL for facts in **one engine** — AGE graph `lineage` plus relational schemas; one backup/HA/transaction, Postgres RLS for masking, managed-Postgres ready.
  - **Agentic-ready:** LLMs write Cypher/SQL well; future agent gets one read-only role over masked views; a future agent tool layer would expose tools (trace_cell, impact_of, explain_hop, readonly_cypher). Design role + views now, build agent later.
  - Escape hatch: AGE stores vertices/edges as ordinary Postgres tables → any Cypher gap (e.g. date-validity predicates over variable-length paths) falls back to a recursive CTE over the same tables inside `LineageStore`.
- **Where it runs (dev): WSL2 Ubuntu 24.04, entirely on D:** (C: is full):
  - `wsl --install Ubuntu-24.04 --location D:\WSL\Ubuntu` (or download rootfs to `D:\WSL\dl` + `wsl --import`); `.wslconfig`: `swapFile=D:\\WSL\\swap.vhdx`. Only WSL itself (already enabled) + tiny `.wslconfig` touch C:.
  - Inside: PGDG apt repo → `postgresql-16` + `postgresql-16-age`; `shared_preload_libraries='age'`, listen on localhost; Windows app connects to `localhost:5432`.
- **Install hygiene:** `UV_CACHE_DIR=D:\Tools\uv-cache`, `npm_config_cache=D:\Tools\npm-cache`; all deps local (`.venv`, `web/node_modules`). No global installs, no winget.
- **Backend:** Python 3.12, FastAPI + uvicorn, psycopg 3, **plain SQL + Cypher** (`schema.sql` applied on startup — no ORM, no Alembic). All graph access behind one `LineageStore` module.
- **Evidence pack:** `reportlab` (PDF, pure-Python, watermark) + `python-docx` (Word). Hop diagram drawn with reportlab primitives (Graphviz not installed). No WeasyPrint (needs GTK on Windows).
- **Frontend:** Vite + React + TypeScript, `@xyflow/react` + `elkjs` (layered lanes), Recharts (waterfall), react-router. Plain CSS with design tokens matching the PDF palette (navy / green / orange / red dashed gap).
- **Auth:** demo role switcher in header → `X-Role` header; API enforces masking/read-only per role. `ponytail:` no real auth, add SSO when leaving demo.

## Repo layout (new)
```
src/lineage_store/   schema.sql, db.py (connection + AGE setup), store.py (traversal/queries), ingest_sql.py, ingest_ol.py, seed/ , evidence.py, audit.py, impact.py
src/lineage_api/     app.py (FastAPI routes), roles.py (masking)
input/corep_pilot/   *.sql — the pilot pipeline (stg → dw → mart → engine) written as INSERT…SELECT so the built-in SQL parser parses the field-level edges
web/                 Vite React app (S01–S12)
tests/               test_store.py, test_api.py (pytest, temp pgserver)
docs/spec/api.md     API contract (written first, shared by backend & frontend agents)
```

## Data model (Postgres)
Graph — AGE graph `lineage` (index on `uid` property; pg_trgm on names for S10 search); every vertex/edge carries properties `uid`, `version`, `valid_from`, `valid_to`, `recorded_at` (point-in-time):
- vertex labels: System, Dataset, Field, Job(hop), Rule, Mapping, Control, Adjustment, ReportTemplate, ReportCell, Gap, Owner
- edge labels: CONTAINS, READS, WRITES, DERIVES(job_id, rule_id, transform_type, contribution), APPLIES, GUARDED_BY, ADJUSTED_BY, DEPENDS_ON(formula), OWNED_BY, HAS_GAP

Relational (same Postgres, joined to graph on `uid`) — Run-time facts: `reporting_context`, `submission`, `run(run_id, job_id, cutoff, started, ended, rerun, records_in, records_out)`, `hop_value(cell_id, submission_id, step, rule_id, hop, amount)`, `control_result(control_id, run_id, status, detail)`, `adjustment(id, amount, reason, maker, checker, times, euc, evidence)`, `mapping_row(mapping_id, version, code, label, target)`, `cell_value(cell_id, submission_id, value)`
Records: `record_contribution(submission_id, cell_id, record_key, counterparty, sector, product, source_system, source_key, value)`, `record_trace(record_key, hop, label, amount, ccy)`
Governance: `certification`, `gap`, `lineage_snapshot(submission_id, cell_id, payload jsonb, hash)`, `evidence_pack(ref, cell, file_path, sha256, watermark, created_by)`, `audit_log(seq, ts, actor, role, action, target, detail, prev_hash, hash)` — append-only, hash-chained.

## Seed data (must reproduce the PDF exactly)
- Context: COREP (EBA DPM), [LEGAL ENTITY], Solo, 30-Jun-2026 v1 (submitted 11-Aug-2026) + 31-Mar-2026 v1.
- Templates list S01 (9 rows, 4 in scope); C 07.00 Corporates grid S02 (5 rows × 5 cols, values from PDF p5; other sheets thinner).
- 10 pilot cells with coverage 7 complete / 2 partial / 1 gap; `C03 = C01 / C02` formula; C01 CET1 = 1,458.7 so 14.82%.
- Pilot cell chain: 3 sources + FX + haircut **Gap**, datasets per p6, 7 hops, T1–T8 with versions/refs (p8), mapping v3.2 vs v3.1 (2 rows differ), 14 controls (13 pass, 1 waived), ADJ-2026-Q2-014 (−18.3).
- Waterfall: 1,312.0 −11.7 −11.9 −26.3 −18.3 −2.1 −1.2 = 1,240.5 (residual 0.0) — computed from `hop_value`, not hardcoded.
- Records: deterministic generator (fixed seed) → 3,418 records whose sector totals match p10 exactly (Q1 total 1,184.3); top-5 contributors fixed; CPTY-•••2764 full trace.
- Forward: `collateral_value` DERIVES contributions (−1.2, −1.1, −48.5, −9.7, −14.2, −10.6); what-if Δ = −contribution × haircut; C02/C03 re-evaluated via DEPENDS_ON formulas → at 15%: +0.2/+0.2/+7.3/+1.5/+2.1/+1.6, TREA +3.3, CET1 −0.5 bps.
- Certification/audit rows from p12.
- Field-level edges for hops 1–4 come from **the built-in SQL parser parsing `input/corep_pilot/*.sql`** via `ingest_sql.py` (reuses `lineage_parser.sql.parser.parse_sql_lineage` and `LineageGraph` in `src/lineage_parser/graph.py`); run facts/controls/adjustments seeded directly.

## API (FastAPI, `/api`, contract in `docs/spec/api.md`)
`GET /contexts`, `/templates`, `/templates/{id}/grid?sheet=`, `/cells/{id}` (summary card), `/cells/{id}/lineage?level=system|dataset|attribute&direction=reverse` (S03), `/cells/{id}/hops/{n}` (S04), `/cells/{id}/transformations` (S05), `/mappings/{id}?version=&compare=`, `/cells/{id}/waterfall` (S06), `/cells/{id}/records?group_by=&compare=` + `/records/{key}/trace` + `POST /records/{key}/reveal` (reason; analyst only; audited), `/cells/{id}/regulator` (narrative from data), `POST /cells/{id}/evidence-pack` (pdf|docx, immutable, sha256, watermark) + `GET /evidence-packs/{ref}`, `/coverage`, `/audit`, `GET /search?q=&kind=` (pg_trgm), `/elements/{id}/impact` (S11), `POST /elements/{id}/what-if` (S12), `POST /impact-report`, `POST /ingest/openlineage` (RunEvent + columnLineage/custom facets), `POST /ingest/sql` (file → SQL/XML parser → graph). Every read of regulator view / export / reveal writes `audit_log`.

## Frontend screens
Shared shell (header chips, nav Reverse/Forward/Coverage, role switcher, footer prev/next + requirement IDs), cell header + 6 tabs. S01 report browser, S02 template grid + side panel, S03 hop graph (ELK lanes, System/Dataset/Attribute toggle, dashed gap), S04 hop detail, S05 transformations + mapping compare, S06 waterfall + adjustment + controls, S07 records + trace + masking toggle, S08 regulator view + generate pack (downloads real file), S09 coverage/audit, S10 search, S11 fan-out graph → links back into S03, S12 what-if slider. Plus journey-map page (p1).

## Execution — multi-agent (Sonnet 5.5 codes, Opus orchestrates/reviews)
0. **Opus (sequential):** set D: cache env; install Ubuntu to `D:\WSL\Ubuntu` (swap on D:) + Postgres 16 + AGE; `uv add` deps; **spike**: create graph, load 20 edges, run date-filtered reverse Cypher traversal from Windows via psycopg — confirm or switch that query to the CTE fallback; `uv add` deps; write `docs/spec/api.md` (JSON shapes for every endpoint) + `schema.sql` skeleton. Checkpoint.
1. **Parallel, background, `model: sonnet`:**
   - **Agent BE-1:** `lineage_store` schema + AGE graph, seed (incl. `input/corep_pilot/*.sql` + `ingest_sql.py`), traversal, API for S01–S07, pytest.
   - **Agent FE-1:** `web/` shell + S01–S07 against contract fixtures (JSON mirrors of `api.md`), then switch to live API via Vite proxy.
2. **Opus review** (`/code-review`, run tests, run app, compare screenshots to PDF p4–10). Fix list back to agents via SendMessage.
3. **Parallel, `model: sonnet`:**
   - **Agent BE-2:** masking/reveal, audit hash chain, snapshots, evidence pack (PDF/DOCX), coverage, search, forward impact, what-if, OpenLineage intake.
   - **Agent FE-2:** S08–S12 + journey map.
4. **Opus final review + end-to-end verification.** Separate directories (`src/` vs `web/`) → no worktrees needed.

## Verification
- `pytest -q` (separate `lineage_test` database in the WSL Postgres): 7 hops on reverse traversal for C07 r0010 c0200; forward from `collateral_value` hits 8 cells / 3 templates / 2 dependency levels; waterfall sums to 1,240.5 with residual 0.0; records total 1,240.5 and Q1 1,184.3; what-if at 15% equals PDF p15 table and −0.5 bps; regulator role never receives unmasked keys; audit chain verifies and detects tampering; evidence pack file sha256 stable and ref unique; point-in-time: T4 mapping v3.1 returned for 31-Mar, v3.2 for 30-Jun; parser tests still pass.
- Run app (`uvicorn lineage_api.app:app` + `npm run dev`), walk the p1 click path end-to-end (4 clicks to hop graph, +2 to evidence pack), screenshot each screen and compare against PDF pages 4–15; open the generated PDF/DOCX pack.

## Environment facts (verified in step 0, 30-Sep-2026) — READ BEFORE CODING
- DB = **PostgreSQL 18 + Apache AGE 1.8.0** in WSL distro `Ubuntu-AGE` (disk `D:\WSL\Ubuntu\ext4.vhdx`, swap on D:). PG18 used (not 16) because it ships the newest AGE.
- Start it with `powershell -File scripts/db.ps1` (keeps the distro alive; WSL stops idle distros → connection timeouts).
- DSN: `host=127.0.0.1 port=5432 user=lineage password=lineage dbname=lineage` (tests: `dbname=lineage_test`). **Never `localhost`** — resolves to ::1, which WSL does not forward; psycopg hangs.
- Extensions `age` and `pg_trgm` already created in both DBs. Per session: `LOAD 'age'; SET search_path = ag_catalog, "$user", public;`
- AGE quirk: `WHERE all(r IN relationships(p) WHERE …)` on variable-length paths raises `no relation entry for relid`. **Use list comprehension instead:**
  `MATCH p=(c:ReportCell {uid:$cell})<-[:DERIVES*1..10]-(s) WITH s, [r IN relationships(p) WHERE r.valid_from > $d OR r.valid_to < $d] AS bad WHERE size(bad) = 0 RETURN DISTINCT s`
  (Cypher params: pass via the 3rd arg of `cypher()`; or inline safely-quoted literals.) Fallback: recursive CTE over `<graph>."DERIVES"` (`start_id`, `end_id`, `properties`).
- Installs: `UV_CACHE_DIR=D:\Tools\uv-cache`, `npm_config_cache=D:\Tools\npm-cache`, `TEMP/TMP=D:\Tools\tmp`. C: has ~1.5 GB free — never install or cache to C:.
- Python deps already added: fastapi, uvicorn[standard], psycopg[binary], reportlab, python-docx, httpx.
