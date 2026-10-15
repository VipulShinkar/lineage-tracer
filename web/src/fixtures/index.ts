// Fixture mode: mirrors docs/spec/api.md with the PDF's exact numbers. Enabled by VITE_USE_FIXTURES=true.
import * as p2 from './phase2'
import type {
  CellHeader, Contexts, Grid, Hop, Lineage, MappingView, RecordTrace, Records, Templates, Transformations, Waterfall, Coverage, CellSummary,
} from '../api'

const CELL = 'C07.00:Corporates:r0010:c0200'
const header = (over: Partial<CellHeader> = {}): CellHeader => ({
  cell_id: CELL, template: 'C 07.00', template_name: 'Credit risk SA', sheet: 'Corporates', row: 'r0010', row_label: 'Total exposures',
  col: 'c0200', col_label: 'Exposure value', value: 1240.5, unit: 'EUR m', coverage: 'partial', coverage_note: '1 known gap', ...over,
})

const contexts: Contexts = {
  report_families: ['COREP (EBA DPM)'], entities: ['[LEGAL ENTITY]'], bases: ['Solo'],
  submissions: [
    { id: '2026-06-30.v1', ref_date: '2026-06-30', version: 'v1', submitted_on: '2026-08-11', label: 'v1 · submitted 11-Aug-2026' },
    { id: '2026-03-31.v1', ref_date: '2026-03-31', version: 'v1', submitted_on: '2026-05-11', label: 'v1 · submitted 11-May-2026' },
  ],
}

const nis = { complete: 0, partial: 0, gap: 0, label: 'Not in scope yet' }
const templates: Templates = {
  templates: [
    { id: 'C01.00', code: 'C 01.00', name: 'Own funds', pilot_cells: 1, cells_total_in_scope: 1, coverage: { complete: 1, partial: 0, gap: 0, label: 'Complete · 1 cell' }, in_scope: true },
    { id: 'C02.00', code: 'C 02.00', name: 'Own funds requirements', pilot_cells: 1, cells_total_in_scope: 1, coverage: { complete: 1, partial: 0, gap: 0, label: 'Complete · 1 cell' }, in_scope: true },
    { id: 'C03.00', code: 'C 03.00', name: 'Capital ratios', pilot_cells: 1, cells_total_in_scope: 1, coverage: { complete: 1, partial: 0, gap: 0, label: 'Complete · via C 01/C 02' }, in_scope: true },
    { id: 'C07.00', code: 'C 07.00', name: 'Credit risk — Standardised Approach', pilot_cells: 7, cells_total_in_scope: 7, coverage: { complete: 4, partial: 2, gap: 1, label: '4 complete · 2 partial · 1 gap' }, in_scope: true },
    { id: 'C08.01', code: 'C 08.01', name: 'Credit risk — IRB', pilot_cells: 0, cells_total_in_scope: 0, coverage: nis, in_scope: false, scope_note: 'After Day 60' },
    { id: 'C34.01', code: 'C 34.01', name: 'Counterparty credit risk', pilot_cells: 0, cells_total_in_scope: 0, coverage: nis, in_scope: false, scope_note: 'After Day 60' },
    { id: 'C16.00', code: 'C 16.00', name: 'Operational risk', pilot_cells: 0, cells_total_in_scope: 0, coverage: nis, in_scope: false, scope_note: 'After Day 60' },
    { id: 'C26.00', code: 'C 26.00', name: 'Large exposures limits', pilot_cells: 0, cells_total_in_scope: 0, coverage: nis, in_scope: false, scope_note: 'After Day 60' },
    { id: 'C47.00', code: 'C 47.00', name: 'Leverage ratio calculation', pilot_cells: 0, cells_total_in_scope: 0, coverage: nis, in_scope: false, scope_note: 'After Day 60' },
  ],
  pilot_scope: {
    total: 10, complete: 7, partial: 2, gap: 1,
    description: 'C 07.00 Corporates (original exposure, exposure value, RWEA), Institutions and Retail (exposure value, RWEA) · C 01.00 CET1 · C 02.00 total risk exposure · C 03.00 CET1 ratio',
  },
  recent_queries: [
    { cell_id: CELL, label: 'C 07.00 · Corporates · Exposure value' },
    { cell_id: 'C03.00:Total:r0010:c0010', label: 'C 03.00 · CET1 ratio' },
    { cell_id: 'C01.00:Total:r0020:c0010', label: 'C 01.00 · Common Equity Tier 1 capital' },
  ],
}

// ---- grid (Corporates has the PDF values; other sheets are thinner, all "not in pilot") ----
const cols = [
  { code: '0010', label: 'Original exposure pre CCF' }, { code: '0030', label: '(–) Value adj. & provisions' },
  { code: '0040', label: 'Exposure net of value adj.' }, { code: '0200', label: 'Exposure value' }, { code: '0220', label: 'RWEA' },
]
const corp: [string, string, boolean, number[]][] = [
  ['0010', 'Total exposures', true, [1265.4, -21.6, 1243.8, 1240.5, 1118.9]],
  ['0020', 'of which: defaulted exposures', false, [38.2, -14.1, 24.1, 23.7, 35.6]],
  ['0030', 'of which: SME', false, [412.6, -5.2, 407.4, 406.1, 297.2]],
  ['0040', 'On-balance sheet exposures', false, [1061.9, -19.9, 1042.0, 1041.4, 962.0]],
  ['0050', 'Off-balance sheet exposures', false, [203.5, -1.7, 201.8, 199.1, 156.9]],
]
function grid(sheet: string): Grid {
  const scale = sheet === 'Corporates' ? 1 : sheet === 'Institutions' ? 0.31 : sheet === 'Retail' ? 0.22 : sheet === 'Total' ? 1.9 : 0.12
  return {
    template: { id: 'C07.00', code: 'C 07.00', name: 'Credit and counterparty credit risks — Standardised Approach' },
    sheets: ['Corporates', 'Institutions', 'Retail', 'Secured by immovable property', 'Total'], sheet, columns: cols,
    rows: corp.map(([code, label, bold, vals]) => ({
      code, label, bold: bold || undefined,
      cells: cols.map((c, i) => {
        let coverage: Coverage = 'not_in_scope'
        if (sheet === 'Corporates' && code === '0010') coverage = i === 3 ? 'partial' : i === 0 || i === 4 ? 'complete' : 'not_in_scope'
        return { col: c.code, cell_id: `C07.00:${sheet.replace(/ /g, '_')}:r${code}:c${c.code}`, value: Math.round(vals[i] * scale * 10) / 10, coverage }
      }),
    })),
  }
}

function cellSummary(id: string): CellSummary {
  const [, sheet = 'Corporates', r = 'r0010', c = 'c0200'] = id.split(':')
  const g = grid(sheet.replace(/_/g, ' '))
  const row = g.rows.find(x => 'r' + x.code === r) ?? g.rows[0]
  const cl = g.columns.find(x => 'c' + x.code === c) ?? g.columns[3]
  const cellv = row.cells.find(x => x.col === cl.code)!
  const pilot = id === CELL
  return {
    cell_header: header({ cell_id: id, sheet, row: r, row_label: row.label, col: c, col_label: cl.label, value: cellv.value,
      coverage: cellv.coverage, coverage_note: pilot ? '1 known gap' : cellv.coverage === 'complete' ? 'complete lineage' : 'not in pilot' }),
    dpm_id: '[datapoint ID]', hops: 7, first_hop_systems: 3, transformations: 8, manual_adjustments: { count: pilot ? 1 : 0, total: pilot ? -18.3 : 0 },
    business_definition: 'Business definition: exposure value after conversion factors and credit risk mitigation, for exposures classified as Corporates.',
    gap_summary: pilot ? 'collateral haircuts' : undefined,
  }
}

// ---- S03 ----
const lineage = (level: Lineage['level']): Lineage => ({
  cell_header: header(), level,
  lanes: ['FIRST HOP', 'STAGING', 'WAREHOUSE', 'REG DATA MART', 'ADJUSTMENTS', 'REG ENGINE', 'SUBMISSION'],
  nodes: level === 'system' ? [
    { uid: 'system:loan_origination', kind: 'source', label: 'Loan origination', lane: 0 },
    { uid: 'system:core_banking', kind: 'source', label: 'Core banking', lane: 0 },
    { uid: 'system:collateral', kind: 'source', label: 'Collateral system', lane: 0 },
    { uid: 'system:fx', kind: 'reference', label: 'FX rates (ECB ref.)', lane: 0 },
    { uid: 'gap:haircut_table', kind: 'gap', label: 'Haircut table — unmapped', lane: 0 },
    { uid: 'system:risk_dwh', kind: 'dataset', label: 'Risk warehouse', lane: 2 },
    { uid: 'system:adj_wb', kind: 'manual', label: 'ADJ-2026-Q2-014', sublabel: 'MANUAL · EUC', lane: 4 },
    { uid: 'system:sa_engine', kind: 'calc', label: 'SA engine: CCF, CRM', lane: 5 },
    { uid: 'cell', kind: 'anchor', label: 'C 07.00 r0010 c0200', lane: 6 },
  ] : [
    { uid: 'system:loan_origination', kind: 'source', label: 'Loan origination', lane: 0 },
    { uid: 'system:core_banking', kind: 'source', label: 'Core banking', lane: 0 },
    { uid: 'system:collateral', kind: 'source', label: 'Collateral system', lane: 0 },
    { uid: 'system:fx', kind: 'reference', label: 'FX rates (ECB ref.)', lane: 0 },
    { uid: 'gap:haircut_table', kind: 'gap', label: 'Haircut table — unmapped', lane: 0 },
    { uid: 'dataset:stg_credit_facilities', kind: 'dataset', label: 'stg_credit_facilities', lane: 1 },
    { uid: 'dataset:stg_collateral', kind: 'dataset', label: 'stg_collateral', lane: 1 },
    { uid: 'dataset:dw_exposure', kind: 'dataset', label: 'dw_exposure', lane: 2 },
    { uid: 'dataset:dw_collateral_alloc', kind: 'dataset', label: 'dw_collateral_alloc', lane: 2 },
    { uid: 'dataset:mart_sa_exposure', kind: 'dataset', label: 'mart_sa_exposure', lane: 3 },
    { uid: 'adj:ADJ-2026-Q2-014', kind: 'manual', label: 'ADJ-2026-Q2-014', sublabel: 'MANUAL · EUC', lane: 4 },
    { uid: 'job:sa_engine', kind: 'calc', label: 'SA engine: CCF, CRM', lane: 5 },
    { uid: 'cell', kind: 'anchor', label: 'C 07.00 r0010 c0200', lane: 6 },
  ],
  edges: level === 'system' ? [
    { src: 'system:loan_origination', dst: 'system:risk_dwh', hop: 1 }, { src: 'system:core_banking', dst: 'system:risk_dwh', hop: 1 },
    { src: 'system:collateral', dst: 'system:risk_dwh', hop: 2 }, { src: 'system:fx', dst: 'system:risk_dwh' },
    { src: 'gap:haircut_table', dst: 'system:risk_dwh', dashed: true },
    { src: 'system:risk_dwh', dst: 'system:adj_wb', hop: 5 }, { src: 'system:adj_wb', dst: 'system:sa_engine', hop: 6 },
    { src: 'system:sa_engine', dst: 'cell', hop: 7 },
  ] : [
    { src: 'system:loan_origination', dst: 'dataset:stg_credit_facilities', hop: 1 }, { src: 'system:core_banking', dst: 'dataset:stg_credit_facilities', hop: 1 },
    { src: 'system:collateral', dst: 'dataset:stg_collateral', hop: 2 }, { src: 'system:fx', dst: 'dataset:stg_collateral' },
    { src: 'gap:haircut_table', dst: 'dataset:stg_collateral', dashed: true },
    { src: 'dataset:stg_credit_facilities', dst: 'dataset:dw_exposure', hop: 3 }, { src: 'dataset:stg_collateral', dst: 'dataset:dw_exposure' },
    { src: 'dataset:stg_collateral', dst: 'dataset:dw_collateral_alloc' },
    { src: 'dataset:dw_exposure', dst: 'dataset:mart_sa_exposure', hop: 4 }, { src: 'dataset:mart_sa_exposure', dst: 'adj:ADJ-2026-Q2-014', hop: 5 },
    { src: 'adj:ADJ-2026-Q2-014', dst: 'job:sa_engine', hop: 6 }, { src: 'dataset:dw_collateral_alloc', dst: 'job:sa_engine' },
    { src: 'job:sa_engine', dst: 'cell', hop: 7 },
  ],
  summary: { hops: 7, first_hop_systems: '3 + FX reference', transformations: 8, manual_adjustments: '1 · −18.3', controls: '13 pass · 1 waived', unexplained_residual: 0.0 },
  known_gaps: [{ uid: 'gap:haircut_table', title: 'Known gap · opened', status: 'opened',
    description: 'Collateral haircut table: source not yet mapped beyond staging. Feeds CRM step (hop 6).',
    owner: 'Collateral data owner', target_date: '2026-12-15' }],
  cell_dependencies: 'This cell feeds C 02.00 (credit risk RWEA via c0220) and C 03.00 CET1 ratio.',
})

// ---- S04 ----
const path = [
  { n: 1, label: 'Loan orig. → staging' }, { n: 2, label: 'Collateral → staging' }, { n: 3, label: 'Staging → warehouse' },
  { n: 4, label: 'Warehouse → mart' }, { n: 5, label: 'Adjustment', manual: true }, { n: 6, label: 'SA engine' }, { n: 7, label: 'XBRL' },
]
const hop3: Omit<Hop, 'cell_header'> = {
  path,
  hop: { n: 3, from: 'stg_credit_facilities', to: 'dw_exposure', mechanism: 'Automated batch load', frequency: 'Daily · month-end run used',
    cutoff: '2026-06-30 23:00', actual_run: '23:42 → 01-Jul 00:18', run_id: '[RUN-ID]', rerun: false },
  records: { in: 48211, out: 47960, value_in: 1312.0, value_out: 1288.4, waterfall_step: 'T2',
    note: '251 intragroup facilities excluded by scope rule T3. Value 1,312.0 → 1,288.4 EUR m after FX (T2) and scope (T3).' },
  ownership: { data_owner: '[Credit risk data owner]', system_owner: '[Risk warehouse owner]', certified: '2026-09-04 · quarterly', open_dq_issues: 'None for this date' },
  mappings: [
    { source_field: 'facility_id', target_field: 'exposure_id', what_happens: 'Pass-through key — kept for record-level drill-down' },
    { source_field: 'drawn_balance', target_field: 'drawn_amount_eur', what_happens: 'FX conversion to EUR (T2)' },
    { source_field: 'undrawn_limit', target_field: 'undrawn_amount_eur', what_happens: 'FX conversion to EUR (T2)' },
    { source_field: 'currency_code', target_field: 'orig_currency', what_happens: 'Pass-through' },
    { source_field: 'counterparty_id', target_field: 'counterparty_id', what_happens: 'Join to counterparty master for sector and group' },
    { source_field: 'intragroup_flag', target_field: '— (filter)', what_happens: 'Intragroup facilities excluded (T3)' },
  ],
  controls: [
    { id: 'H3_count', name: 'Record count completeness', status: 'pass', detail: '48,211 received = 48,211 sent by source' },
    { id: 'H3_gl_recon', name: 'GL reconciliation — drawn balances', status: 'pass', detail: 'Difference 0.02% · tolerance 0.10%' },
    { id: 'H3_fx', name: 'FX rate availability', status: 'pass', detail: 'All 14 currencies had a 30-Jun rate' },
    { id: 'H3_intragroup', name: 'Intragroup exclusion reasonableness', status: 'pass', detail: '251 records excluded · within expected range' },
  ],
}
function hop(n: number): Hop {
  if (n === 3) return { cell_header: header(), ...hop3 }
  const p = path[n - 1]
  const [from, to] = p.label.includes('→') ? p.label.split(' → ') : [p.label, p.label]
  return {
    cell_header: header(), path,
    hop: { n, from, to, mechanism: p.manual ? 'Manual adjustment (EUC workbook)' : 'Automated batch load', frequency: 'Daily · month-end run used',
      cutoff: '2026-06-30 23:00', actual_run: '01:10 → 01:32', run_id: '[RUN-ID]', rerun: false },
    records: { in: n === 5 ? 1 : 47960, out: n === 5 ? 1 : 47960, value_in: 1262.1, value_out: 1243.8, note: p.manual ? 'One counterparty reclassified (ADJ-2026-Q2-014).' : 'No records dropped at this hop.' },
    ownership: hop3.ownership,
    mappings: [{ source_field: 'exposure_id', target_field: 'exposure_id', what_happens: 'Pass-through key' }],
    controls: [{ id: `H${n}_check`, name: 'Hop control', status: 'pass', detail: 'Within tolerance' }],
  }
}

// ---- S05 ----
const mapping = (compare?: string): MappingView => ({
  uid: 'mapping:product_to_class', name: 'product → exposure class', version: '3.2', effective_from: '2026-04-01',
  rows: [
    { code: 'TL-CORP', label: 'Term loan — corporate', target: 'Corporates' },
    { code: 'RCF-CORP', label: 'Revolving credit facility', target: 'Corporates' },
    { code: 'RCF-SME', label: 'Revolving facility — SME', target: 'Corporates', changed: compare ? true : undefined },
    { code: 'TF-GUAR', label: 'Trade finance guarantee', target: 'Corporates' },
    { code: 'LN-BANK', label: 'Interbank loan', target: 'Institutions' },
    { code: 'RCF-BANK', label: 'Facility to credit institution', target: 'Institutions', changed: compare ? true : undefined },
  ],
  previous_version: '3.1', differs_in: 2,
})
const transformations = (): Transformations => ({
  cell_header: header(), as_of: '2026-06-30',
  transformations: [
    { id: 'T1', type: 'PASS-THROUGH', hop: 'Hop 1–2', amount: 0.0, description: 'Balances, limits and collateral values copied as received from source systems; no change in value.', version: 'v1.0', owner: 'Data owner', reference: { label: 'Interface spec' } },
    { id: 'T2', type: 'FX CONVERSION', hop: 'Hop 3', amount: -11.7, description: 'Amounts in 14 currencies converted to EUR using the ECB reference rate of 30-Jun-2026.', version: 'v2.1', effective_from: '2026-01-01', owner: 'Finance data lead', reference: { label: 'FX policy §4' } },
    { id: 'T3', type: 'SCOPE FILTER', hop: 'Hop 3', amount: -11.9, description: 'Facilities to other group entities excluded from this solo exposure class (251 facilities).', version: 'v1.4', owner: 'Reg reporting policy', reference: { label: 'Scope policy §2' } },
    { id: 'T4', type: 'MAPPING', hop: 'Hop 4', amount: -26.3, description: 'Product and counterparty type mapped to SA exposure class; exposures to banks move to Institutions.', version: 'v3.2', effective_from: '2026-04-01', owner: 'Reg reporting policy', reference: { label: 'CRR Art. 112' } },
    { id: 'T5', type: 'MANUAL ADJUSTMENT', hop: 'Hop 5', amount: -18.3, description: 'One counterparty reclassified from Corporates to Institutions after licence review (ADJ-2026-Q2-014).', version: '', owner: 'Maker-checker approved', reference: { label: 'Open evidence' }, manual: true, adjustment_id: 'ADJ-2026-Q2-014', approved_on: '2026-07-08' },
    { id: 'T6', type: 'DERIVATION', hop: 'Hop 6', amount: -2.1, description: 'Off-balance sheet items multiplied by the credit conversion factor for their risk bucket.', version: 'Engine rule v5.0', owner: 'Methodology', reference: { label: 'CRR Art. 111' } },
    { id: 'T7', type: 'DERIVATION', hop: 'Hop 6', amount: -1.2, description: 'Eligible financial collateral reduces exposure value (comprehensive method). Uses haircut table — known gap.', version: 'Engine rule v5.0', owner: 'Methodology', reference: { label: 'CRR Art. 223' } },
    { id: 'T8', type: 'SCALING', hop: 'Hop 7', amount: 0.0, description: 'Values expressed in the reporting unit and rounded for XBRL; no material effect.', version: 'v1.0', owner: 'Reg reporting', reference: { label: 'Reporting ITS' } },
  ],
  mapping: mapping(),
  dependency: {
    text: 'This cell’s RWEA (c0220) flows into C 02.00 total risk exposure amount, which is the denominator of the C 03.00 CET1 ratio. Numerator comes from C 01.00 CET1 capital.',
    formula: 'C 03.00 CET1 ratio = C 01.00 CET1 ÷ C 02.00 TREA',
  },
})

// ---- S06 ----
const step = (key: string, label: string, sublabel: string, amount: number, kind: 'total' | 'delta' | 'manual', type: 'rule' | 'adjustment' | 'hop', id: string) =>
  ({ key, label, sublabel, amount, kind, link: { type, id } })
const wf = (): Waterfall => ({
  cell_header: header(),
  steps: [
    step('source', 'Source', 'Hops 1–2 · in orig. ccy', 1312.0, 'total', 'hop', '1'),
    step('fx', 'FX to EUR', 'T2 · hop 3', -11.7, 'delta', 'rule', 'rule:T2'),
    step('scope', 'Intragroup out', 'T3 · hop 3', -11.9, 'delta', 'rule', 'rule:T3'),
    step('map', 'Class mapping', 'T4 · hop 4', -26.3, 'delta', 'rule', 'rule:T4'),
    step('manual', 'Manual adj.', 'T5 · hop 5', -18.3, 'manual', 'adjustment', 'adj:ADJ-2026-Q2-014'),
    step('ccf', 'CCF', 'T6 · hop 6', -2.1, 'delta', 'rule', 'rule:T6'),
    step('crm', 'CRM', 'T7 · hop 6', -1.2, 'delta', 'rule', 'rule:T7'),
    step('reported', 'Reported', 'Hop 7 · XBRL', 1240.5, 'total', 'hop', '7'),
  ],
  residual: 0.0, tolerance: 0.1, within_tolerance: true,
  adjustment: { id: 'ADJ-2026-Q2-014', amount: -18.3,
    description: 'Counterparty [CPTY-•••4821] reclassified from Corporates to Institutions after banking licence confirmed. One-off, not recurring.',
    maker: '[Analyst A]', maker_at: '2026-07-07T16:12:00', checker: '[Manager B]', checker_at: '2026-07-08T09:40:00',
    source: 'Adjustments workbook v3 (EUC-0142, high risk)', evidence: { label: 'licence register extract', url: '#' } },
  controls: { summary: '13 pass · 1 waived · 0 fail', items: [
    { hop: 'H1', name: 'Loan feed record count', status: 'pass' }, { hop: 'H2', name: 'Collateral feed record count', status: 'pass' },
    { hop: 'H3', name: 'GL reconciliation — drawn', status: 'pass' }, { hop: 'H3', name: 'Intragroup exclusion check', status: 'pass' },
    { hop: 'H4', name: 'Class vs prior quarter movement', status: 'pass' }, { hop: 'H5', name: 'Adjustment evidence attached', status: 'pass' },
    { hop: 'H6', name: 'EBA validation rules', status: 'pass' },
    { hop: 'H1', name: 'Core banking feed record count', status: 'pass' }, { hop: 'H2', name: 'Collateral valuation age < 1 year', status: 'waived' },
    { hop: 'H3', name: 'FX rate availability', status: 'pass' }, { hop: 'H4', name: 'Unmapped products = 0', status: 'pass' },
    { hop: 'H5', name: 'Adjustment maker ≠ checker', status: 'pass' }, { hop: 'H6', name: 'Engine input = mart output', status: 'pass' },
    { hop: 'H7', name: 'XBRL = engine output', status: 'pass' },
  ] },
})

// ---- S07 ----
const r1 = (n: number) => Math.round(n * 10) / 10
const grp = (key: string, records: number, current: number, compare: number) => ({ key, records, current, compare, change: r1(current - compare) })
const groupSets: Record<string, ReturnType<typeof grp>[]> = {
  sector: [grp('Manufacturing', 812, 402.1, 391.4), grp('Real estate activities', 604, 288.7, 270.2), grp('Wholesale and retail trade', 911, 214.9, 206.3),
    grp('Energy', 143, 131.6, 120.9), grp('Transport and storage', 287, 97.4, 95.1), grp('Other sectors', 661, 105.8, 100.4)],
  product: [grp('Term loan', 1620, 702.3, 668.9), grp('Revolving facility', 902, 311.4, 296.0), grp('Trade guarantee', 511, 143.6, 132.1), grp('Other products', 385, 83.2, 87.3)],
  source_system: [grp('Loan origination', 2201, 896.4, 846.9), grp('Core banking', 1217, 344.1, 337.4)],
}
const records = (group_by: string, masked: boolean): Records => {
  const groups = groupSets[group_by] ?? groupSets.sector
  const sum = (f: (g: (typeof groups)[0]) => number) => r1(groups.reduce((a, g) => a + f(g), 0))
  const m = (v: string) => v
  return {
    cell_header: header(), contributing_records: 3418, drilldown_total: 1240.5, equals_reported: true, groups,
    total: { records: sum(g => g.records), current: sum(g => g.current), compare: sum(g => g.compare), change: sum(g => g.change) },
    top: [
      { record_key: 'REC-1107', counterparty: m('CPTY-•••1107'), sector_product: 'Energy · term loan', source: 'Loan orig.', source_key: 'LOS-FAC-00••••31', value: 42.8 },
      { record_key: 'REC-3390', counterparty: m('CPTY-•••3390'), sector_product: 'Real estate · revolving facility', source: 'Core banking', source_key: 'CBS-ACC-7•••••02', value: 37.5 },
      { record_key: 'REC-0815', counterparty: m('CPTY-•••0815'), sector_product: 'Manufacturing · term loan', source: 'Loan orig.', source_key: 'LOS-FAC-00••••77', value: 31.2 },
      { record_key: 'REC-5521', counterparty: m('CPTY-•••5521'), sector_product: 'Wholesale · trade guarantee', source: 'Core banking', source_key: 'CBS-GTE-4•••••19', value: 28.9 },
      { record_key: 'REC-2764', counterparty: m('CPTY-•••2764'), sector_product: 'Transport · term loan', source: 'Loan orig.', source_key: 'LOS-FAC-00••••58', value: 25.4 },
    ],
    masking: { masked, can_reveal: masked && role_ === 'analyst' },
  }
}
let role_ = 'analyst'
const trace = (key: string): RecordTrace => {
  const t = records('sector', true).top.find(x => x.record_key === key) ?? records('sector', true).top[4]
  const v = t.value
  return {
    record_key: key, title: `${t.counterparty} · ${t.sector_product.split(' · ').reverse().join(' · ')}`,
    steps: [
      { hop: 'H1', label: `Loan origination · facility ${t.source_key}`, sublabel: 'Drawn balance as received', amount: r1(v * 1.0866 * 100) / 100, ccy: 'USD' },
      { hop: 'H3', label: 'Converted to EUR (T2)', sublabel: 'ECB reference rate 30-Jun-2026', amount: v, ccy: 'EUR' },
      { hop: 'H3', label: 'Scope check (T3)', sublabel: 'Not intragroup · kept', amount: v },
      { hop: 'H4', label: 'Mapped to Corporates (T4)', sublabel: 'Product TL-CORP · mapping v3.2', amount: v },
      { hop: 'H5', label: 'No manual adjustment', sublabel: 'Not in ADJ-2026-Q2-014 scope', amount: v },
      { hop: 'H6', label: 'CCF / CRM (T6, T7)', sublabel: 'On-balance · no eligible collateral', amount: v },
      { hop: 'H7', label: 'Contribution to reported cell', sublabel: 'C 07.00 r0010 c0200', amount: v },
    ],
  }
}

const ok = <T,>(x: T) => x
export function fixture(method: string, rawPath: string, body: unknown, role: string): unknown {
  role_ = role
  const [p, qs = ''] = rawPath.split('?')
  const query = new URLSearchParams(qs)
  const seg = p.split('/').filter(Boolean).map(decodeURIComponent)
  return new Promise((resolve, reject) => setTimeout(() => {
    try { resolve(route(method, seg, query, body, role)) } catch (e) { reject(e) }
  }, 60))
}
function route(method: string, s: string[], q: URLSearchParams, body: unknown, role: string): unknown {
  const [a, b, c, d] = s
  if (a === 'contexts') return ok(contexts)
  if (a === 'templates' && !b) return ok(templates)
  if (a === 'templates' && c === 'grid') return grid(q.get('sheet') ?? 'Corporates')
  if (a === 'mappings') return mapping(q.get('compare') ?? undefined)
  if (a === 'search') return p2.search(q.get('kind') ?? 'all')
  if (a === 'coverage') return p2.coverage()
  if (a === 'audit') return p2.audit()
  if (a === 'elements' && c === 'impact') return p2.impact(b)
  if (a === 'elements' && c === 'what-if') return p2.whatIf(Number((body as { haircut_pct: number }).haircut_pct))
  if (a === 'records' && c === 'trace') return trace(b)
  if (a === 'records' && c === 'reveal' && method === 'POST') {
    if (role !== 'analyst') throw new Error('Role not allowed to reveal identifiers')
    if (!(body as { reason?: string })?.reason) throw new Error('A reason is required')
    return { counterparty: 'CPTY-00012764', source_key: 'LOS-FAC-00123458' }
  }
  if (a === 'cells') {
    if (!c) return cellSummary(b)
    if (c === 'lineage') return lineage((q.get('level') as Lineage['level']) ?? 'dataset')
    if (c === 'hops') return hop(Number(d))
    if (c === 'transformations') return transformations()
    if (c === 'waterfall') return wf()
    if (c === 'regulator') return p2.regulator(header({ cell_id: b }))
    if (c === 'evidence-pack') return { ref: 'EP-2026-Q2-0042', sha256: 'a3f5c1d2e9b84f60718d2c4b5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f7081', download_url: '/api/evidence-packs/EP-2026-Q2-0042', created_at: '2026-11-13T10:05:00' }
    if (c === 'records') return records(q.get('group_by') ?? 'sector', true)
  }
  throw new Error(`No fixture for ${s.join('/')}`)
}
