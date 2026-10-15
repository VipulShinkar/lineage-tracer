// Phase 2 fixtures (S08–S12), numbers from PDF pages 11–15.
import type { Audit, CellHeader, Coverage_, Impact, Regulator, SearchResults, WhatIf } from '../api'

const r1 = (n: number) => Math.round(n * 10) / 10

export const regulator = (header: CellHeader): Regulator => ({
  cell_header: header,
  narrative: 'The 1,240.5m EUR reported for Corporates exposure value starts in three source systems: loan origination, core banking and the collateral system. Balances were loaded on 30 June, converted to euro at the ECB reference rate, and exposures to other group entities were removed (−23.6m). Products were mapped to exposure classes, moving bank exposures to Institutions (−26.3m). One counterparty was reclassified by hand to Institutions after its banking licence was confirmed (−18.3m, approved by a separate checker). The calculation engine then applied conversion factors and eligible collateral (−3.3m). Every movement is explained; no unexplained difference remains.',
  stages: [
    { label: 'Source systems', value: 1312.0, note: '3 systems + FX rates' },
    { label: 'Prepared', value: 1288.4, note: 'EUR, intragroup removed' },
    { label: 'Classified', value: 1262.1, note: 'Exposure-class mapping' },
    { label: 'Adjusted', value: 1243.8, note: '1 manual, approved', manual: true },
    { label: 'Reported', value: 1240.5, note: 'After CCF and collateral' },
  ],
  stats: { hops: 7, transformations: 8, manual_adjustments: 1, controls_passed: '13 / 14', unexplained: 0.0, records: 3418 },
  limitations: [{ text: 'The haircut table used when recognising collateral (−1.2m effect) is not yet traced beyond staging. Owner: collateral data owner. Target date: 15-Dec-2026.' }],
  evidence: {
    next_ref: 'EP-2026-Q2-0042', linked_request: '[REF]',
    sections: [['cover', 'Cover sheet and sign-off block'], ['narrative', 'Plain-English narrative'], ['hops', 'Hop diagram'], ['sourcing', 'Sourcing at each hop'],
      ['transformations', 'Transformations with versions'], ['waterfall', 'Value waterfall'], ['adjustments', 'Manual adjustments and approvals'],
      ['controls', 'Control results'], ['records', 'Top contributors (masked)'], ['limitations', 'Known limitations']].map(([key, label]) => ({ key, label, default: true })),
    formats: ['pdf', 'docx'], last_pack: { ref: 'EP-2026-Q1-0017', created_on: '2026-05-14' },
  },
})

export const coverage = (): Coverage_ => ({
  refreshed_at: '2026-11-12T22:10:00',
  kpis: { cells_complete: '7 / 10', cells_note: '2 partial · 1 gap', hops_certified_pct: 86, hops_note: '43 of 50 hops', unexplained_breaks: 0,
    adjustments_approved: '4 / 4', open_gaps: 1, open_gaps_note: 'target 15-Dec-2026', evidence_packs: 6 },
  by_template: [
    { template: 'C 01.00', name: 'Own funds', cells: 1, complete: 1, partial: 0, gap: 0, status: 'Complete' },
    { template: 'C 02.00', name: 'Own funds requirements', cells: 1, complete: 1, partial: 0, gap: 0, status: 'Complete' },
    { template: 'C 03.00', name: 'Capital ratios', cells: 1, complete: 1, partial: 0, gap: 0, status: 'Complete' },
    { template: 'C 07.00', name: 'Credit risk SA', cells: 7, complete: 4, partial: 2, gap: 1, status: 'Partial · 1 gap' },
  ],
  certification: [
    { owner: 'Credit risk data owner', nodes: 14, pct: 100, status: 'Certified 04-Nov' }, { owner: 'Finance / GL data owner', nodes: 9, pct: 100, status: 'Certified 06-Nov' },
    { owner: 'Collateral data owner', nodes: 8, pct: 63, status: 'Due 20-Nov' }, { owner: 'Reg reporting (engine rules)', nodes: 12, pct: 92, status: 'Due 20-Nov' },
    { owner: 'Treasury data owner', nodes: 7, pct: 71, status: 'Due 20-Nov' },
  ],
})

export const audit = (): Audit => ({
  chain_valid: true, retention: '7 years',
  entries: [
    ['2026-11-13T10:05:00', 'Supervisor [A]', 'generated evidence pack', 'EP-2026-Q2-0042', 'C 07.00 r0010 c0200'],
    ['2026-11-13T10:02:00', 'Supervisor [A]', 'opened regulator view', 'C 07.00 r0010 c0200', '30-Jun-2026 v1'],
    ['2026-11-12T16:48:00', 'Analyst [B]', 'revealed an identifier', 'CPTY-•••2764', 'reason: supervisory query [REF]'],
    ['2026-11-12T14:20:00', 'Analyst [B]', 'exported drill-down (masked)', 'C 07.00 Corporates', 'top 20'],
    ['2026-11-06T11:15:00', 'GL data owner', 'certified lineage', '9 nodes', 'Q4 cycle'],
    ['2026-11-04T09:30:00', 'Credit risk data owner', 'certified lineage', '14 nodes', 'Q4 cycle'],
    ['2026-11-02T17:02:00', 'Lineage admin', 'changed metadata', 'Hop 6 · T7 description updated', '(approved)'],
    ['2026-10-30T15:40:00', 'Collateral data owner', 'opened gap record', 'Haircut table', 'target 15-Dec-2026'],
  ].map(([ts, actor, action, target, detail], i) => ({ seq: 8 - i, ts, actor, role: 'analyst', action, target, detail })),
})

const SEARCH: SearchResults['results'] = [
  { uid: 'field:collateral_master.collateral_value', kind: 'field', name: 'collateral_master.collateral_value', subtitle: 'Collateral system · first hop · owner: collateral data owner', feeds_cells: 8, verb: 'Feeds' },
  { uid: 'field:stg_collateral.market_value_eur', kind: 'field', name: 'stg_collateral.market_value_eur', subtitle: 'Staging · hop 2 · pass-through of the field above', feeds_cells: 8, verb: 'Feeds' },
  { uid: 'rule:T7', kind: 'rule', name: 'T7 · Credit risk mitigation, comprehensive method', subtitle: 'SA engine · hop 6 · engine rule v5.0', feeds_cells: 8, verb: 'Feeds' },
  { uid: 'mapping:collateral_eligibility', kind: 'mapping', name: 'Collateral type → eligibility v2.0', subtitle: 'Regulatory data mart · hop 4', feeds_cells: 6, verb: 'Feeds' },
  { uid: 'control:H2_coll_age', kind: 'control', name: 'Collateral valuation age < 1 year', subtitle: 'Hop 2 · waived on 30-Jun-2026 run', feeds_cells: 8, verb: 'Guards' },
]
export const search = (kind: string) => ({ results: SEARCH.filter(x => kind === 'all' || x.kind === kind) })

const cellNode = (uid: string, label: string, col: string) => ({ uid, label, sublabel: `C 07.00 · ${col}`, lane: 4, kind: 'cell' as const })
const CELLS = ['Corporates:r0010:c0200', 'Corporates:r0010:c0220', 'Institutions:r0010:c0200', 'Institutions:r0010:c0220', 'Retail:r0010:c0200', 'Retail:r0010:c0220']
export const impact = (uid: string): Impact => ({
  element: { uid, name: 'collateral_master.collateral_value', kind: 'field' },
  stats: { templates: 3, cells: 8, entities: 1, dependency_levels: 2 },
  lanes: ['START', 'STAGING', 'WAREHOUSE', 'REG ENGINE', 'C 07.00 CELLS', 'DEPENDENT CELLS'],
  nodes: [
    { uid, label: 'collateral_value', sublabel: 'FIRST HOP', lane: 0, kind: 'start' },
    { uid: 'dataset:stg_collateral', label: 'stg_collateral', sublabel: 'HOP 2', lane: 1, kind: 'hop' },
    { uid: 'dataset:dw_collateral_alloc', label: 'dw_collateral_alloc', sublabel: 'HOP 3', lane: 2, kind: 'hop' },
    { uid: 'job:sa_engine', label: 'SA engine: CRM', sublabel: 'HOP 6 · T7', lane: 3, kind: 'hop' },
    cellNode('C07.00:Corporates:r0010:c0200', 'Corporates · exposure value', 'c0200'), cellNode('C07.00:Corporates:r0010:c0220', 'Corporates · RWEA', 'c0220'),
    cellNode('C07.00:Institutions:r0010:c0200', 'Institutions · exposure value', 'c0200'), cellNode('C07.00:Institutions:r0010:c0220', 'Institutions · RWEA', 'c0220'),
    cellNode('C07.00:Retail:r0010:c0200', 'Retail · exposure value', 'c0200'), cellNode('C07.00:Retail:r0010:c0220', 'Retail · RWEA', 'c0220'),
    { uid: 'C02.00:Main:r0010:c0010', label: 'Total risk exposure amount', sublabel: 'C 02.00', lane: 5, kind: 'dependent' },
    { uid: 'C03.00:Main:r0010:c0010', label: 'CET1 ratio', sublabel: 'C 03.00', lane: 5, kind: 'dependent' },
  ],
  edges: [
    { src: uid, dst: 'dataset:stg_collateral' }, { src: 'dataset:stg_collateral', dst: 'dataset:dw_collateral_alloc' }, { src: 'dataset:dw_collateral_alloc', dst: 'job:sa_engine' },
    ...CELLS.map(c => ({ src: 'job:sa_engine', dst: `C07.00:${c}` })),
    { src: 'C07.00:Corporates:r0010:c0220', dst: 'C02.00:Main:r0010:c0010' }, { src: 'C07.00:Institutions:r0010:c0220', dst: 'C02.00:Main:r0010:c0010' },
    { src: 'C07.00:Retail:r0010:c0220', dst: 'C02.00:Main:r0010:c0010' }, { src: 'C02.00:Main:r0010:c0010', dst: 'C03.00:Main:r0010:c0010' },
  ],
  impacted: [
    ...['Corporates · exposure value', 'Corporates · RWEA', 'Institutions · exposure value', 'Institutions · RWEA', 'Retail · exposure value', 'Retail · RWEA']
      .map((label, i) => ({ cell_id: `C07.00:${CELLS[i]}`, label, ref: `C 07.00 r0010 ${CELLS[i].split(':')[2]}` })),
    { cell_id: 'C02.00:Main:r0010:c0010', label: 'Total risk exposure amount', ref: 'C 02.00 · via RWEA' },
    { cell_id: 'C03.00:Main:r0010:c0010', label: 'CET1 ratio', ref: 'C 03.00 · via C 02.00' },
  ],
})

const BASE: [string, string, string, number, number][] = [
  ['C07.00:Corporates:r0010:c0200', 'Corporates · exposure value', 'C 07.00 r0010 c0200', 1240.5, -1.2],
  ['C07.00:Corporates:r0010:c0220', 'Corporates · RWEA', 'C 07.00 r0010 c0220', 1118.9, -1.1],
  ['C07.00:Institutions:r0010:c0200', 'Institutions · exposure value', 'C 07.00 r0010 c0200', 612.3, -48.5],
  ['C07.00:Institutions:r0010:c0220', 'Institutions · RWEA', 'C 07.00 r0010 c0220', 248.6, -9.7],
  ['C07.00:Retail:r0010:c0200', 'Retail · exposure value', 'C 07.00 r0010 c0200', 905.8, -14.2],
  ['C07.00:Retail:r0010:c0220', 'Retail · RWEA', 'C 07.00 r0010 c0220', 612.4, -10.6],
]
export function whatIf(haircutPct: number): WhatIf {
  const f = haircutPct / 100
  const mk = (cell_id: string, label: string, ref: string, reported: number, from: number, change?: number) => {
    const ch = change ?? r1(-from * f)
    const pct = Math.round(Math.abs(ch) / reported * 10000) / 100
    return { cell_id, label, ref, reported, from_element: from, estimated: r1(reported + ch), change: ch, pct_of_cell: pct,
      threshold: (pct >= 1 ? 'above' : pct >= 0.5 ? 'near' : 'within') as 'within' | 'near' | 'above' }
  }
  const rows = BASE.map(b => mk(...b))
  const rwea = rows.filter(r => r.ref.endsWith('c0220'))
  rows.push(mk('C02.00:Main:r0010:c0010', 'Total risk exposure amount', 'C 02.00 · via RWEA', 9842.6,
    r1(rwea.reduce((a, r) => a + r.from_element, 0)), r1(rwea.reduce((a, r) => a + r.change, 0))))
  const above = rows.filter(r => r.threshold === 'above').length
  const bps = Math.round((-0.5 * haircutPct / 15) * 10) / 10
  return {
    rows,
    ratio: { cell_id: 'C03.00:Main:r0010:c0010', label: 'CET1 ratio (C 03.00)', reported_pct: 14.82, estimated_pct: 14.82, change_bps: bps, threshold_bps: 10 },
    decision: Math.abs(bps) >= 10
      ? { level: 'resubmit', title: 'Resubmission likely required', text: 'The capital ratio moves by 10 bps or more. Escalate to Head of Reg Reporting.' }
      : above > 0 ? { level: 'discuss', title: 'Discuss with Regulatory Affairs', text: `${above} cell(s) move more than 1%. Capital ratio impact stays below 10 bps. Record the decision against the incident.` }
      : { level: 'none', title: 'No resubmission needed', text: 'All cells move by less than 1% and the ratio stays below 10 bps. Record the decision against the incident.' },
    cde_footprint: [['drawn_balance', 10], ['fx_rate', 10], ['product_code', 9], ['counterparty_type', 9], ['collateral_value', 8]].map(([field, cells]) => ({ field: field as string, cells: cells as number, of: 10 })),
    method_note: 'EUR millions. Estimates, not recalculated returns: method = linear propagation through recorded transformations; reviewed by methodology before use.',
  }
}
