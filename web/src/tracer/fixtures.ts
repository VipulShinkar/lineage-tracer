// Fixture mode for the Tracer: two demo traces (C90 via Superset, C 07.00 with a pause at loans_db). Time-driven simulation.
import type { Connection, Header, Hop, HopStatus, LineageData, Pack, Report, Step, Trace } from './api'

const sleep = (ms = 80) => new Promise(r => setTimeout(r, ms))

const C90_ROWS: [string, string, number][] = [
  ['COM', 'DELTA', 3916.49], ['EQ', 'DELTA', 2104.77], ['FX', 'DELTA', 3867.06], ['GIRR', 'DELTA', 5120.4], ['ALL', 'DELTA', 9626.96],
]
const c90Report: Report = {
  report_id: 'rep-c90', file_name: 'corep_c90_2026-06-30.pdf',
  meta: { title: 'COREP C90 Report', return_type: 'COREP', entity: '[LEGAL ENTITY]', ref_date: '2026-06-30', version: 'v1', delivered_to: 'Regulator portal', template: 'C90' },
  tables: [{
    id: 'c90', title: 'C90', key_columns: ['consolidation_group', 'risk_class', 'sensitivity_type'], value_columns: ['reported_value_usd'], unit: 'USD',
    rows: C90_ROWS.map(([rc, t, v], i) => ({ index: i, key: { consolidation_group: 'GROUP-01', risk_class: rc, sensitivity_type: t }, values: { reported_value_usd: v } })),
  }],
}
const c07Rows: [string, string, number[]][] = [
  ['0010', 'Total exposures', [1265.4, 1243.8, 1240.5, 1118.9]], ['0040', 'On-balance sheet', [1061.9, 1042.0, 1041.4, 962.0]], ['0050', 'Off-balance sheet', [203.5, 201.8, 199.1, 156.9]],
]
const c07Cols = ['0010', '0040', '0200', '0220']
const c07Table = (id: string, title: string, k: number) => ({
  id, title, key_columns: ['Row', 'Item'], value_columns: c07Cols, unit: 'EUR m',
  rows: c07Rows.map(([r, item, v], i) => ({ index: i, key: { Row: r, Item: item }, values: Object.fromEntries(c07Cols.map((c, j) => [c, Math.round(v[j] * k * 10) / 10])) })),
})
const c07Report: Report = {
  report_id: 'rep-c07', file_name: 'corep_2026-06-30_v1.xbrl',
  meta: { title: 'C 07.00 Corporates', return_type: 'COREP', entity: '[LEGAL ENTITY] · Solo', ref_date: '2026-06-30', version: 'v1', template: 'C 07.00' },
  tables: [c07Table('c0700-corp', 'C 07.00 · Credit risk SA · Corporates', 1), c07Table('c0700-inst', 'C 07.00 · Credit risk SA · Institutions', 0.31)],
}

type Def = { header: Header; steps: Omit<Step, 'n' | 'status'>[]; pauseAt?: number; pending?: Trace['pending']; lineage: LineageData }
const st = (system: string, system_type: Step['system_type'], held: string[], from: string[], by: string[], sor = false): Omit<Step, 'n' | 'status'> =>
  ({ system, system_type, attribute_held_in: held, sourced_from: from, consumed_by: by, sourced_from_is_sor: sor || undefined })

const hop = (n: number, status: HopStatus, from: string, to: string, held: string[], src: string[], transformation: string, consumed_by: string, evidence: Hop['evidence']): Hop =>
  ({ n, status, from, to, attribute_held_in: held, sourced_from: src, transformation, consumed_by, evidence })
const sql = (t: string, s: string, w = '') => `INSERT INTO ${t}\nSELECT ${s}\n${w}`.trim()
const VER = 'definition sha256 1a2b3c4d… · captured 2026-10-06'

// ---- C 07.00 ----
const c07Lineage: LineageData = {
  header: { direction: 'reverse', template: 'C 07.00', label: 'C 07.00 · Corporates · r0010 c0200', value: 1240.5, unit: 'EUR m', ref_date: '2026-06-30' },
  summary: { hops: 9, proven: 7, code_derived: 2, unresolved: 0, systems_of_record: 3, title: 'EUR 1,240.5m traced to 3 systems of record' },
  lanes: ['system_of_record', 'staging', 'warehouse', 'data_mart', 'calc_engine', 'reporting_layer'],
  nodes: [
    { id: 'fac', system: 'loans_db', object: 'los.facility', lane: 'system_of_record', kind: 'sor' },
    { id: 'fx', system: 'FX rates feed', object: 'ref_fx_rates', lane: 'system_of_record', kind: 'sor' },
    { id: 'col', system: 'collateral_db', object: 'col.collateral', lane: 'system_of_record', kind: 'sor' },
    { id: 'sfac', system: 'staging', object: 'stg_facilities', lane: 'staging', kind: 'intermediate' },
    { id: 'scol', system: 'staging', object: 'stg_collateral', lane: 'staging', kind: 'intermediate' },
    { id: 'dwe', system: 'warehouse', object: 'dw_exposure', lane: 'warehouse', kind: 'intermediate' },
    { id: 'dwc', system: 'warehouse', object: 'dw_collateral_alloc', lane: 'warehouse', kind: 'intermediate' },
    { id: 'mart', system: 'data mart', object: 'mart_sa_exposure', lane: 'data_mart', kind: 'intermediate' },
    { id: 'calc', system: 'SA engine', object: 'calc_sa_exposure', lane: 'calc_engine', kind: 'intermediate' },
    { id: 'rpt', system: 'reporting_db', object: 'C 07.00 r0010 c0200', lane: 'reporting_layer', kind: 'anchor' },
  ],
  edges: [
    { from: 'fac', to: 'sfac', hop: 1, status: 'proven' }, { from: 'col', to: 'scol', hop: 2, status: 'proven' },
    { from: 'sfac', to: 'dwe', hop: 3, status: 'proven' }, { from: 'fx', to: 'dwe', hop: 4, status: 'proven' },
    { from: 'scol', to: 'dwc', hop: 5, status: 'code_derived' }, { from: 'dwe', to: 'mart', hop: 6, status: 'proven' },
    { from: 'dwc', to: 'calc', hop: 7, status: 'code_derived' }, { from: 'mart', to: 'calc', hop: 8, status: 'proven' },
    { from: 'calc', to: 'rpt', hop: 9, status: 'proven' },
  ],
  hops: [
    hop(1, 'proven', 'los.facility', 'stg_facilities', ['drawn_balance', 'undrawn_limit'], ['los.facility.drawn_balance', 'los.facility.undrawn_limit'], 'Copied daily from the loan origination system via a foreign table; no business logic.', 'stg_facilities (hop 3)',
      { code: 'staging: foreign table stg_facilities → loans_db.los.facility', sql: sql('stg_facilities', 'facility_id, drawn_balance, undrawn_limit, currency, intragroup_flag', 'FROM los.facility;'), version: VER, log: 'pg_stat_statements · 1 call · INSERT INTO stg_facilities …', reconciliation: 'Recalculated 5,412 rows agree to stored values' }),
    hop(2, 'proven', 'col.collateral', 'stg_collateral', ['market_value'], ['col.collateral.market_value'], 'Copied daily from the collateral system via a foreign table.', 'stg_collateral (hop 5)',
      { code: 'staging: foreign table stg_collateral → collateral_db.col.collateral', sql: sql('stg_collateral', 'collateral_id, facility_id, market_value, currency', 'FROM col.collateral;'), version: VER, log: 'pg_stat_statements · 1 call · INSERT INTO stg_collateral …', reconciliation: 'Recalculated 3,208 rows agree to stored values' }),
    hop(3, 'proven', 'stg_facilities', 'dw_exposure', ['drawn_eur', 'undrawn_eur'], ['drawn_balance', 'undrawn_limit', 'currency', 'intragroup_flag'], 'Converted to EUR at the 30-Jun-2026 rate; 251 intragroup facilities excluded.', 'mart_sa_exposure (hop 6)',
      { code: 'sql/sp_load_exposure.sql:88–131', sql: sql('dw_exposure', 'f.facility_id, f.drawn_balance * r.rate AS drawn_eur,\n       f.undrawn_limit * r.rate AS undrawn_eur', 'FROM stg_facilities f JOIN ref_fx_rates r ON r.ccy = f.currency\nWHERE f.intragroup_flag = false;'), version: 'commit 7c1e0b4 · deployed 12-Jun-2026', log: 'query log 01-Jul 00:02:14 · INSERT INTO dw_exposure', reconciliation: 'Recalculated 1,288.4 agrees to stored value' }),
    hop(4, 'proven', 'ref_fx_rates', 'dw_exposure', ['rate'], ['ref_fx_rates.rate'], 'ECB reference rates joined on currency and reporting date.', 'dw_exposure (hop 3)',
      { code: 'sql/sp_load_exposure.sql:92', version: VER, log: 'OpenLineage run 5d3f…', reconciliation: 'Rates agree to the ECB feed for 30-Jun-2026' }),
    hop(5, 'code_derived', 'stg_collateral', 'dw_collateral_alloc', ['allocated_value_eur'], ['stg_collateral.market_value'], 'Collateral market value allocated pro rata across facilities and converted to EUR.', 'calc_sa_exposure (hop 7)',
      { code: 'sql/sp_alloc_collateral.sql:12–60', sql: sql('dw_collateral_alloc', 'c.facility_id,\n       c.market_value * r.rate * w.share AS allocated_value_eur', 'FROM stg_collateral c JOIN alloc_weights w USING (facility_id)\nJOIN ref_fx_rates r ON r.ccy = c.currency;'), version: VER, log: 'query log 01-Jul 00:03:41 · INSERT INTO dw_collateral_alloc', reconciliation: 'Not reconciled: allocation weights are not retained' }),
    hop(6, 'proven', 'dw_exposure', 'mart_sa_exposure', ['off_bal_eur'], ['dw_exposure.undrawn_eur'], 'Undrawn amounts converted with the credit conversion factor.', 'calc_sa_exposure (hop 8)',
      { code: 'sql/vw_mart_sa_exposure.sql:1–24', sql: 'SELECT facility_id, undrawn_eur * ccf AS off_bal_eur\nFROM dw_exposure;', version: VER, log: 'view definition (pg_views)', reconciliation: 'Recalculated 199.1 agrees to stored value' }),
    hop(7, 'code_derived', 'dw_collateral_alloc', 'calc_sa_exposure', ['exposure_value'], ['dw_collateral_alloc.allocated_value_eur'], 'Collateral allocation reduces the exposure value (financial collateral comprehensive method).', 'rpt.c0700_facts (hop 9)',
      { code: 'sa_engine: function calc.sp_sa_exposure lines 40–102', version: VER, log: 'pg_stat_statements · 1 call', reconciliation: 'Not reconciled: haircut table not found' }),
    hop(8, 'proven', 'mart_sa_exposure', 'calc_sa_exposure', ['exposure_value'], ['mart_sa_exposure.off_bal_eur'], 'Off-balance sheet exposure added to the on-balance sheet exposure.', 'rpt.c0700_facts (hop 9)',
      { code: 'sa_engine: function calc.sp_sa_exposure lines 12–39', version: VER, log: 'pg_stat_statements · 1 call', reconciliation: 'Recalculated 1,240.5 agrees to stored value' }),
    hop(9, 'proven', 'calc_sa_exposure', 'C 07.00 r0010 c0200', ['value'], ['calc_sa_exposure.exposure_value'], 'Aggregated by exposure class and row; rounded to EUR m.', 'XBRL writer → COREP v1',
      { code: 'reporting_db: view rpt.c0700_facts', sql: 'SELECT row_code, col_code, SUM(exposure_value) AS value\nFROM calc_sa_exposure GROUP BY 1, 2;', version: VER, log: 'view definition (pg_views)', reconciliation: 'Recalculated 1,240.5 agrees to reported value' }),
  ],
}
// ---- column-level shape (C 07.00): made-up column lists; '*' marks in-path columns ----
const NUM = /(_eur|_balance|_value|_limit|rate|_pct|rwea|^value)$/
const cols = (list: string) => list.split(',').map(x => { const name = x.replace('*', ''); return { name, data_type: NUM.test(name) ? 'numeric(18,2)' : /_date$/.test(name) ? 'date' : /_flag$/.test(name) ? 'boolean' : 'text', in_path: x.endsWith('*') } })
const meta: Record<string, [NonNullable<LineageData['nodes'][number]['service']>, string, string, string, NonNullable<LineageData['nodes'][number]['entity_type']>, string]> = {
  fac: ['postgresql', 'loans_db', 'los', 'facility', 'table', 'facility_id,drawn_balance*,undrawn_limit*,currency*,intragroup_flag,customer_id,maturity_date,provision_pct'],
  fx: ['sqlite', 'market_data.db', '', 'fx_rates', 'table', 'ccy,rate*,rate_date'],
  col: ['postgresql', 'collateral_db', 'col', 'collateral', 'table', 'collateral_id,facility_id,market_value*,currency,haircut_pct'],
  sfac: ['postgresql', 'staging', 'public', 'stg_facilities', 'table', 'facility_id,drawn_balance*,undrawn_limit*,currency*,intragroup_flag,provision_pct'],
  scol: ['postgresql', 'staging', 'public', 'stg_collateral', 'table', 'collateral_id,market_value*,currency,haircut_pct'],
  dwe: ['postgresql', 'dwh', 'public', 'dw_exposure', 'table', 'facility_id,drawn_eur*,undrawn_eur*,provision_pct'],
  dwc: ['postgresql', 'dwh', 'public', 'dw_collateral_alloc', 'table', 'facility_id,allocated_value_eur*,haircut_pct'],
  mart: ['postgresql', 'dwh', 'public', 'mart_sa_exposure', 'view', 'facility_id,off_bal_eur*,exposure_class'],
  calc: ['postgresql', 'sa_engine', 'public', 'calc_sa_exposure', 'table', 'facility_id,exposure_value*,rwea'],
  rpt: ['postgresql', 'reporting_db', 'rpt', 'c0700_facts', 'table', 'row_code,col_code,value*'],
}
for (const n of c07Lineage.nodes) { const [service, database, schema, name, entity_type, c] = meta[n.id]; Object.assign(n, { service, database, schema: schema || undefined, name, entity_type, columns: cols(c) }) }
const ce = (hop: number, from_node: string, from_column: string, to_node: string, to_column: string, transformation: string) => ({ hop, from_node, from_column, to_node, to_column, transformation })
c07Lineage.column_edges = [
  ce(1, 'fac', 'drawn_balance', 'sfac', 'drawn_balance', 'pass-through'), ce(1, 'fac', 'undrawn_limit', 'sfac', 'undrawn_limit', 'pass-through'), ce(1, 'fac', 'currency', 'sfac', 'currency', 'pass-through'),
  ce(2, 'col', 'market_value', 'scol', 'market_value', 'pass-through'),
  ce(3, 'sfac', 'drawn_balance', 'dwe', 'drawn_eur', 'drawn_balance * rate'), ce(3, 'sfac', 'undrawn_limit', 'dwe', 'undrawn_eur', 'undrawn_limit * rate'), ce(3, 'sfac', 'currency', 'dwe', 'drawn_eur', 'join on currency'),
  ce(4, 'fx', 'rate', 'dwe', 'drawn_eur', 'rate'), ce(4, 'fx', 'rate', 'dwe', 'undrawn_eur', 'rate'),
  ce(5, 'scol', 'market_value', 'dwc', 'allocated_value_eur', 'market_value * rate * share'),
  ce(6, 'dwe', 'undrawn_eur', 'mart', 'off_bal_eur', 'undrawn_eur * ccf'),
  ce(7, 'dwc', 'allocated_value_eur', 'calc', 'exposure_value', 'exposure - allocated_value_eur'),
  ce(8, 'mart', 'off_bal_eur', 'calc', 'exposure_value', 'SUM'),
  ce(9, 'calc', 'exposure_value', 'rpt', 'value', 'SUM'),
]
// ---- business logic (made up) ----
const NODE_DESC: Record<string, string> = {
  fac: 'Loan origination system master of corporate facilities.', dwe: 'Warehouse exposure per facility, converted to EUR with intragroup facilities excluded.',
  calc: 'Standardised-approach exposure value per facility after credit conversion and collateral.', rpt: 'Reporting facts feeding the COREP C 07.00 template.',
}
for (const n of c07Lineage.nodes) if (NODE_DESC[n.id]) n.description = NODE_DESC[n.id]
for (const c of c07Lineage.nodes.find(n => n.id === 'dwe')!.columns!) if (c.name === 'drawn_eur') c.description = 'Drawn balance converted to EUR at the reporting date rate.'
const RULES: Record<number, [string, string[]]> = {
  3: ['Convert drawn and undrawn amounts to EUR for the exposure warehouse.', ['Intragroup facilities are excluded', 'Amounts use the ECB rate on the reporting date']],
  6: ['Apply the credit conversion factor to undrawn commitments.', ['Off-balance sheet exposure = undrawn amount x CCF']],
  8: ['Add off-balance sheet exposure to the on-balance sheet exposure.', ['Exposure value is reported net of value adjustments']],
  9: ['Aggregate facilities into the template cell.', ['Rows follow the exposure class; values are rounded to EUR m']],
}
for (const h of c07Lineage.hops) if (RULES[h.n]) { h.purpose = RULES[h.n][0]; h.business_rules = RULES[h.n][1] }
const BR: Record<string, string> = { 'drawn_eur': 'Drawn balance in EUR', 'undrawn_eur': 'Undrawn limit in EUR', 'off_bal_eur': 'Off-balance sheet exposure after CCF', 'exposure_value': 'Exposure value after credit risk mitigation', 'value': 'Reported cell value' }
for (const c of c07Lineage.column_edges!) if (BR[c.to_column]) c.business_rule = BR[c.to_column]
// whole-report variant: no single value
const c07Report_: Header = { ...c07Lineage.header, value: null, label: 'C 07.00 · Corporates · whole report' }

const c07Steps = [
  st('reporting_db', 'postgresql', ['rpt.c0700_facts.value'], ['calc_sa_exposure.exposure_value'], ['XBRL writer → COREP v1']),
  st('sa_engine', 'postgresql', ['calc_sa_exposure.exposure_value'], ['mart_sa_exposure.off_bal_eur', 'dw_collateral_alloc.allocated_value_eur'], ['rpt.c0700_facts']),
  st('dwh', 'postgresql', ['mart_sa_exposure.off_bal_eur'], ['dw_exposure.undrawn_eur'], ['calc_sa_exposure']),
  st('dwh', 'postgresql', ['dw_collateral_alloc.allocated_value_eur'], ['stg_collateral.market_value'], ['calc_sa_exposure']),
  st('dwh', 'postgresql', ['dw_exposure.drawn_eur', 'undrawn_eur'], ['stg_facilities.drawn_balance', 'ref_fx_rates.rate'], ['mart_sa_exposure']),
  st('staging', 'postgresql', ['stg_collateral.market_value'], ['col.collateral.market_value'], ['dw_collateral_alloc']),
  st('collateral_db', 'postgresql', ['col.collateral.market_value'], ['System of record'], ['stg_collateral'], true),
  st('staging', 'postgresql', ['ref_fx_rates.rate'], ['System of record (ECB feed)'], ['dw_exposure'], true),
  st('staging', 'postgresql', ['stg_facilities.drawn_balance'], ['los.facility.drawn_balance'], ['dw_exposure']),
  st('loans_db', 'postgresql', ['los.facility.drawn_balance'], ['System of record'], ['stg_facilities'], true),
]
const c07: Def = {
  header: c07Lineage.header, steps: c07Steps, pauseAt: 9, lineage: c07Lineage,
  pending: { system: 'loans_db', type: 'postgresql', host_hint: 'loans-db.sandbox:5432', database_hint: 'los', phase: 'connect',
    message: 'stg_facilities.drawn_balance is sourced from los.facility on loans_db. Read-only connection details are required to continue.' },
}

const c07All: Def = { header: c07Report_, steps: c07Steps, pauseAt: 9, pending: c07.pending, lineage: { ...c07Lineage, header: c07Report_ } }

// ---- C90 ----
const c90Header: Header = { direction: 'reverse', template: 'C90', label: 'C90 · GROUP-01 · FX · DELTA', value: 3867.06, unit: 'USD', ref_date: '2026-06-30' }
const c90Lineage: LineageData = {
  header: c90Header,
  summary: { hops: 7, proven: 6, code_derived: 1, unresolved: 0, systems_of_record: 2, title: 'USD 3,867.06 traced to 2 systems of record' },
  lanes: ['system_of_record', 'staging', 'warehouse', 'calc_engine', 'reporting_layer', 'report_tool'],
  nodes: [
    { id: 'ts', system: 'trading_db', object: 'trade_sensitivity', lane: 'system_of_record', kind: 'sor' },
    { id: 'mfx', system: 'market_data.db', object: 'fx_rates', lane: 'system_of_record', kind: 'sor' },
    { id: 'sts', system: 'staging', object: 'stg_sensitivity', lane: 'staging', kind: 'intermediate' },
    { id: 'sfx', system: 'staging', object: 'ref_fx_rates', lane: 'staging', kind: 'intermediate' },
    { id: 'dws', system: 'dwh', object: 'dw_sensitivity_usd', lane: 'warehouse', kind: 'intermediate' },
    { id: 'sbm', system: 'frtb_engine', object: 'calc_sbm_sensitivity', lane: 'calc_engine', kind: 'intermediate' },
    { id: 'rc90', system: 'reporting_db', object: 'rpt_c90_facts', lane: 'reporting_layer', kind: 'intermediate' },
    { id: 'ss', system: 'Superset', object: 'COREP C90 Report', lane: 'report_tool', kind: 'anchor' },
  ],
  edges: [
    { from: 'ts', to: 'sts', hop: 1, status: 'proven' }, { from: 'mfx', to: 'sfx', hop: 2, status: 'code_derived' },
    { from: 'sts', to: 'dws', hop: 3, status: 'proven' }, { from: 'sfx', to: 'dws', hop: 4, status: 'proven' },
    { from: 'dws', to: 'sbm', hop: 5, status: 'proven' }, { from: 'sbm', to: 'rc90', hop: 6, status: 'proven' }, { from: 'rc90', to: 'ss', hop: 7, status: 'proven' },
  ],
  hops: [
    hop(1, 'proven', 'trade_sensitivity', 'stg_sensitivity', ['sensitivity'], ['trade_sensitivity.sensitivity'], 'Copied via a foreign table; native currency retained.', 'dw_sensitivity_usd (hop 3)', { code: 'staging: foreign table → trading_db', version: VER, log: 'pg_stat_statements · 1 call', reconciliation: 'Recalculated 8,114 rows agree' }),
    hop(2, 'code_derived', 'fx_rates', 'ref_fx_rates', ['rate'], ['market_data.db.fx_rates.rate'], 'Loaded from the SQLite market data file by an ETL job.', 'dw_sensitivity_usd (hop 4)', { code: 'ETL job load_fx_rates', version: VER, log: 'OpenLineage run 9a41…', reconciliation: 'Not reconciled: SQLite file has no query log' }),
    hop(3, 'proven', 'stg_sensitivity', 'dw_sensitivity_usd', ['sensitivity_usd'], ['stg_sensitivity.sensitivity', 'currency'], 'Converted to USD at the reporting date rate.', 'calc_sbm_sensitivity (hop 5)', { code: 'dwh: function etl.sp_load_sensitivity lines 20–64', sql: sql('dw_sensitivity_usd', 's.*, s.sensitivity * r.rate AS sensitivity_usd', 'FROM stg_sensitivity s JOIN ref_fx_rates r ON r.ccy = s.currency;'), version: VER, log: 'pg_stat_statements · 1 call', reconciliation: 'Recalculated 3,867.06 agrees to stored value' }),
    hop(4, 'proven', 'ref_fx_rates', 'dw_sensitivity_usd', ['rate'], ['ref_fx_rates.rate'], 'FX rate joined on currency.', 'dw_sensitivity_usd (hop 3)', { code: 'dwh: function etl.sp_load_sensitivity line 41', version: VER, log: 'pg_stat_statements · 1 call', reconciliation: 'Rates agree' }),
    hop(5, 'proven', 'dw_sensitivity_usd', 'calc_sbm_sensitivity', ['sensitivity_usd_sum'], ['dw_sensitivity_usd.sensitivity_usd'], 'Aggregated by risk class and sensitivity type.', 'rpt_c90_facts (hop 6)', { code: 'frtb_engine: function calc.sp_sbm lines 5–48', sql: 'SELECT risk_class, sensitivity_type, SUM(sensitivity_usd)\nFROM dw_sensitivity_usd GROUP BY 1, 2;', version: VER, log: 'pg_stat_statements · 1 call', reconciliation: 'Recalculated 3,867.06 agrees' }),
    hop(6, 'proven', 'calc_sbm_sensitivity', 'rpt_c90_facts', ['reported_value_usd'], ['calc_sbm_sensitivity.sensitivity_usd_sum'], 'Published to the reporting table unchanged.', 'COREP C90 Report (hop 7)', { code: 'reporting_db: view rpt_c90_facts', version: VER, log: 'view definition (pg_views)', reconciliation: 'Recalculated 3,867.06 agrees' }),
    hop(7, 'proven', 'rpt_c90_facts', 'COREP C90 Report', ['reported_value_usd'], ['rpt_c90_facts.reported_value_usd'], 'Superset table chart reads the dataset directly.', 'Regulatory report', { code: 'Superset chart "COREP C90 Report" → dataset rpt_c90_facts', version: VER, log: 'Superset chart data re-run', reconciliation: 'Chart value 3,867.06 agrees' }),
  ],
}
const c90: Def = {
  header: c90Header, lineage: c90Lineage,
  steps: [
    st('Superset', 'superset', ['COREP C90 Report.reported_value_usd'], ['rpt_c90_facts.reported_value_usd'], ['Regulatory report']),
    st('reporting_db', 'postgresql', ['rpt_c90_facts.reported_value_usd'], ['calc_sbm_sensitivity.sensitivity_usd_sum'], ['COREP C90 Report']),
    st('frtb_engine', 'postgresql', ['calc_sbm_sensitivity.sensitivity_usd_sum'], ['dw_sensitivity_usd.sensitivity_usd'], ['rpt_c90_facts']),
    st('dwh', 'postgresql', ['dw_sensitivity_usd.sensitivity_usd'], ['stg_sensitivity.sensitivity', 'ref_fx_rates.rate'], ['calc_sbm_sensitivity']),
    st('staging', 'postgresql', ['ref_fx_rates.rate'], ['System of record (market_data.db)'], ['dw_sensitivity_usd'], true),
    st('trading_db', 'postgresql', ['trade_sensitivity.sensitivity'], ['System of record'], ['stg_sensitivity'], true),
  ],
}

// ---- simulation ----
const STEP_MS = 700
type Run = { def: Def; t0: number; resumedAt?: number }
const runs = new Map<string, Run>()
let seq = 0

function view(id: string, r: Run): Trace {
  const { def } = r
  const total = def.steps.length
  const pauseAt = def.pauseAt ?? Infinity
  const k = Math.floor((Date.now() - r.t0) / STEP_MS)
  const resumed = r.resumedAt !== undefined
  const revealed = resumed ? Math.min(total, pauseAt + Math.floor((Date.now() - r.resumedAt!) / STEP_MS)) : Math.min(k, pauseAt, total)
  const paused = !resumed && k >= pauseAt && pauseAt < total
  const complete = revealed >= total
  const steps: Step[] = []
  for (let i = 0; i < Math.min(total, revealed + 1); i++) {
    const s = def.steps[i]
    if (i < revealed) steps.push({ ...s, n: i + 1, status: 'identified' })
    else if (paused && i === pauseAt) steps.push({ n: i + 1, system: def.pending!.system, system_type: def.pending!.type, attribute_held_in: [], sourced_from: [], consumed_by: [], status: 'connection_required' })
    else if (!complete) steps.push({ ...s, n: i + 1, attribute_held_in: [], sourced_from: [], consumed_by: [], status: 'scanning' })
  }
  const done = steps.filter(s => s.status === 'identified')
  return {
    trace_id: id, header: def.header, steps, status: complete ? 'complete' : paused ? 'connection_required' : 'running',
    pending: paused ? def.pending : undefined,
    stats: {
      systems_connected: new Set(done.map(s => s.system)).size, sor_reached: done.filter(s => s.sourced_from_is_sor).length,
      sor_known: def.steps.filter(s => s.sourced_from_is_sor).length,
      branches_outstanding: complete ? 0 : paused ? 1 : Math.max(1, total - revealed - 1),
    },
  }
}

export async function tracerFixture(method: string, path: string, body: unknown): Promise<unknown> {
  await sleep(); const s = path.split('/').filter(Boolean)
  if (s[0] === 'reports' && method === 'POST') {
    const f = (body as FormData).get('file') as File | null
    return /c90|\.pdf$/i.test(f?.name ?? '') ? { ...c90Report, file_name: f?.name ?? c90Report.file_name } : { ...c07Report, file_name: f?.name ?? c07Report.file_name }
  }
  if (s[0] === 'traces' && !s[1] && method === 'POST') {
    const b = body as { report_id: string; mode?: string }
    const id = `tr-${++seq}`
    runs.set(id, { def: b.report_id === 'rep-c90' ? c90 : b.mode === 'report' ? c07All : c07, t0: Date.now() })
    return { trace_id: id }
  }
  const r = runs.get(s[1])
  if (!r) throw new Error('Trace not found')
  if (s[2] === undefined) return view(s[1], r)
  if (s[2] === 'connections') {
    const c = body as Connection
    if (!c.password) throw new Error('could not connect: password authentication failed for user "' + c.user + '"')
    r.resumedAt = Date.now()
    return { ok: true }
  }
  if (s[2] === 'lineage') return r.def.lineage
  if (s[2] === 'evidence-pack') return { ref: 'EP-' + s[1].toUpperCase(), sha256: 'e3b0c44298fc1c149afbf4c8996fb924', download_url: '/api/evidence-packs/EP-' + s[1] } satisfies Pack
  throw new Error('Not found')
}
