// Typed client mirroring docs/spec/api.md. VITE_USE_FIXTURES=true serves src/fixtures instead of the live API.
import { useEffect, useState } from 'react'
import { fixture } from './fixtures'

export type Coverage = 'complete' | 'partial' | 'gap' | 'not_in_scope'
export type ControlStatus = 'pass' | 'fail' | 'waived'
export type Role = 'analyst' | 'supervisor' | 'data_owner' | 'head_of_reg'

export type CellHeader = {
  cell_id: string; template: string; template_name: string; sheet: string
  row: string; row_label: string; col: string; col_label: string
  value: number; unit: 'EUR m'; coverage: Coverage; coverage_note: string
}
export type Contexts = {
  report_families: string[]; entities: string[]; bases: string[]
  submissions: { id: string; ref_date: string; version: string; submitted_on: string; label: string }[]
}
export type Templates = {
  templates: { id: string; code: string; name: string; pilot_cells: number; cells_total_in_scope: number
    coverage: { complete: number; partial: number; gap: number; label: string }; in_scope: boolean; scope_note?: string }[]
  pilot_scope: { total: number; complete: number; partial: number; gap: number; description: string }
  recent_queries: { cell_id: string; label: string }[]
}
export type Grid = {
  template: { id: string; code: string; name: string }; sheets: string[]; sheet: string
  columns: { code: string; label: string }[]
  rows: { code: string; label: string; bold?: boolean; cells: { col: string; cell_id: string; value: number; coverage: Coverage }[] }[]
}
export type CellSummary = {
  cell_header: CellHeader; dpm_id: string; hops: number; first_hop_systems: number; transformations: number
  manual_adjustments: { count: number; total: number }; business_definition: string; gap_summary?: string
}
export type SearchResults = {
  results: { uid: string; kind: string; name: string; subtitle: string; feeds_cells: number; verb: 'Feeds' | 'Guards' }[]
}
export type Level = 'system' | 'dataset' | 'attribute'
export type Lineage = {
  cell_header: CellHeader; level: Level; lanes: string[]
  nodes: { uid: string; kind: 'source' | 'reference' | 'gap' | 'dataset' | 'field' | 'manual' | 'calc' | 'anchor'; label: string; sublabel?: string; lane: number }[]
  edges: { src: string; dst: string; hop?: number; dashed?: boolean }[]
  summary: { hops: number; first_hop_systems: string; transformations: number; manual_adjustments: string; controls: string; unexplained_residual: number }
  known_gaps: { uid: string; title: string; description: string; owner: string; target_date: string; status: string }[]
  cell_dependencies: string
}
export type Hop = {
  cell_header: CellHeader
  path: { n: number; label: string; manual?: boolean }[]
  hop: { n: number; from: string; to: string; mechanism: string; frequency: string; cutoff: string; actual_run: string; run_id: string; rerun: boolean }
  records: { in: number; out: number; note: string; value_in: number; value_out: number; waterfall_step?: string }
  ownership: { data_owner: string; system_owner: string; certified: string; open_dq_issues: string }
  mappings: { source_field: string; target_field: string; what_happens: string }[]
  controls: { id: string; name: string; status: ControlStatus; detail: string }[]
}
export type MappingView = {
  uid: string; name: string; version: string; effective_from: string
  rows: { code: string; label: string; target: string; changed?: boolean }[]
  previous_version?: string; differs_in?: number
}
export type Transformations = {
  cell_header: CellHeader; as_of: string
  transformations: { id: string; type: string; hop: string; amount: number; description: string; version: string; effective_from?: string
    owner: string; reference: { label: string; url?: string }; manual?: boolean; adjustment_id?: string; approved_on?: string }[]
  mapping: MappingView
  dependency: { text: string; formula: string }
}
export type Waterfall = {
  cell_header: CellHeader
  steps: { key: string; label: string; sublabel: string; amount: number; kind: 'total' | 'delta' | 'manual'; link: { type: 'rule' | 'adjustment' | 'hop'; id: string } }[]
  residual: number; tolerance: number; within_tolerance: boolean
  adjustment: { id: string; amount: number; description: string; maker: string; maker_at: string; checker: string; checker_at: string
    source: string; evidence: { label: string; url: string } }
  controls: { summary: string; items: { hop: string; name: string; status: ControlStatus }[] }
}
export type Records = {
  cell_header: CellHeader; contributing_records: number; drilldown_total: number; equals_reported: boolean
  groups: { key: string; records: number; current: number; compare: number; change: number }[]
  total: { records: number; current: number; compare: number; change: number }
  top: { record_key: string; counterparty: string; sector_product: string; source: string; source_key: string; value: number }[]
  masking: { masked: boolean; can_reveal: boolean }
}
export type RecordTrace = {
  record_key: string; title: string
  steps: { hop: string; label: string; sublabel: string; amount: number; ccy?: 'USD' | 'EUR' }[]
}
export type Reveal = { counterparty: string; source_key: string }

export type Regulator = {
  cell_header: CellHeader; narrative: string
  stages: { label: string; value: number; note: string; manual?: boolean }[]
  stats: { hops: number; transformations: number; manual_adjustments: number; controls_passed: string; unexplained: number; records: number }
  limitations: { text: string }[]
  evidence: { next_ref: string; linked_request: string; sections: { key: string; label: string; default: boolean }[]
    formats: string[]; last_pack?: { ref: string; created_on: string } }
}
export type EvidencePack = { ref: string; sha256: string; download_url: string; created_at: string }
export type Coverage_ = {
  refreshed_at: string
  kpis: { cells_complete: string; cells_note: string; hops_certified_pct: number; hops_note: string; unexplained_breaks: number
    adjustments_approved: string; open_gaps: number; open_gaps_note: string; evidence_packs: number }
  by_template: { template: string; name: string; cells: number; complete: number; partial: number; gap: number; status: string }[]
  certification: { owner: string; nodes: number; pct: number; status: string }[]
}
export type Audit = {
  chain_valid: boolean; retention: string
  entries: { seq: number; ts: string; actor: string; role: string; action: string; target: string; detail?: string }[]
}
export type Impact = {
  element: { uid: string; name: string; kind: string }
  stats: { templates: number; cells: number; entities: number; dependency_levels: number }
  lanes: string[]
  nodes: { uid: string; label: string; sublabel?: string; lane: number; kind: 'start' | 'hop' | 'cell' | 'dependent' }[]
  edges: { src: string; dst: string }[]
  impacted: { cell_id: string; label: string; ref: string }[]
}
export type WhatIf = {
  rows: { cell_id: string; label: string; ref: string; reported: number; from_element: number; estimated: number; change: number
    pct_of_cell: number; threshold: 'within' | 'near' | 'above' }[]
  ratio: { cell_id: string; label: string; reported_pct: number; estimated_pct: number; change_bps: number; threshold_bps: number }
  decision: { level: 'discuss' | 'none' | 'resubmit'; title: string; text: string }
  cde_footprint: { field: string; cells: number; of: number }[]
  method_note: string
}

// ---- role (demo switcher -> X-Role header) ----
export const ROLES: { id: Role; label: string }[] = [
  { id: 'analyst', label: 'Analyst' }, { id: 'supervisor', label: 'Supervisor' },
  { id: 'data_owner', label: 'Data owner' }, { id: 'head_of_reg', label: 'Head of Reg Reporting' },
]
let role: Role = 'analyst'
try { role = (localStorage.getItem('role') as Role) || 'analyst' } catch { /* storage unavailable */ }
export const getRole = () => role
export function setRole(r: Role) {
  role = r
  try { localStorage.setItem('role', r) } catch { /* ignore */ }
}

// Selected submission (`sub` query param on every call). '' = server default (latest submitted).
let sub = ''
export const getSub = () => sub
export const setSubId = (id: string) => { sub = id }

const USE_FIXTURES = import.meta.env.VITE_USE_FIXTURES === 'true'

function withSub(path: string) {
  if (!sub || path.startsWith('/contexts') || /[?&]sub=/.test(path)) return path
  return path + (path.includes('?') ? '&' : '?') + 'sub=' + encodeURIComponent(sub)
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const res = await fetch('/api' + withSub(path), {
    method,
    headers: { 'X-Role': role, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const d = (await res.json()).detail
      detail = typeof d === 'string' ? d : d ? JSON.stringify(d) : detail
    } catch { /* not json */ }
    throw new Error(detail)
  }
  return res
}
async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (USE_FIXTURES) return fixture(method, withSub(path), body, role) as T
  return (await send(method, path, body)).json()
}
/** File download (evidence pack, impact report). */
async function requestBlob(method: string, path: string, body?: unknown): Promise<Blob> {
  if (USE_FIXTURES) return new Blob([`Fixture file for ${path}
`], { type: 'text/plain' })
  return (await send(method, path, body)).blob()
}
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const q = (o: Record<string, string | undefined>) => {
  const p = Object.entries(o).filter(([, v]) => v).map(([k, v]) => `${k}=${encodeURIComponent(v!)}`).join('&')
  return p ? '?' + p : ''
}
const cell = (id: string) => `/cells/${encodeURIComponent(id)}`

export const api = {
  contexts: () => request<Contexts>('GET', '/contexts'),
  templates: () => request<Templates>('GET', '/templates'),
  grid: (t: string, sheet?: string) => request<Grid>('GET', `/templates/${t}/grid${q({ sheet })}`),
  cell: (id: string) => request<CellSummary>('GET', cell(id)),
  search: (text: string, kind = 'all') => request<SearchResults>('GET', `/search${q({ q: text, kind })}`),
  lineage: (id: string, level: Level) => request<Lineage>('GET', `${cell(id)}/lineage${q({ level })}`),
  hop: (id: string, n: number) => request<Hop>('GET', `${cell(id)}/hops/${n}`),
  transformations: (id: string) => request<Transformations>('GET', `${cell(id)}/transformations`),
  mapping: (uid: string, version?: string, compare?: string, cellId?: string) =>
    request<MappingView>('GET', `/mappings/${uid}${q({ version, compare, cell: cellId })}`),
  waterfall: (id: string) => request<Waterfall>('GET', `${cell(id)}/waterfall`),
  records: (id: string, group_by: string, compare?: string) =>
    request<Records>('GET', `${cell(id)}/records${q({ group_by, compare, top: '5' })}`),
  trace: (key: string) => request<RecordTrace>('GET', `/records/${encodeURIComponent(key)}/trace`),
  regulator: (id: string) => request<Regulator>('GET', `${cell(id)}/regulator`),
  evidencePack: (id: string, sections: string[], format: string) =>
    request<EvidencePack>('POST', `${cell(id)}/evidence-pack`, { sections, format }),
  download: (url: string) => requestBlob('GET', url.replace(/^\/api/, '')),
  coverage: () => request<Coverage_>('GET', '/coverage'),
  audit: (limit = 8) => request<Audit>('GET', `/audit${q({ limit: String(limit) })}`),
  impact: (uid: string) => request<Impact>('GET', `/elements/${encodeURIComponent(uid)}/impact`),
  whatIf: (uid: string, haircut_pct: number, incident_ref?: string, reason?: string) =>
    request<WhatIf>('POST', `/elements/${encodeURIComponent(uid)}/what-if`, { haircut_pct, incident_ref, reason }),
  impactReport: (element_uid: string, haircut_pct: number, incident_ref?: string) =>
    requestBlob('POST', '/impact-report', { element_uid, haircut_pct, incident_ref }),
  reveal: (key: string, reason: string) => request<Reveal>('POST', `/records/${encodeURIComponent(key)}/reveal`, { reason }),
}

/** Fetch hook: refetches when deps or the role change (role is in deps via caller). */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[]) {
  const [state, set] = useState<{ data?: T; error?: string; loading: boolean }>({ loading: true })
  useEffect(() => {
    let live = true
    set(s => ({ ...s, loading: true, error: undefined }))
    fn().then(data => live && set({ data, loading: false }), e => live && set({ error: String(e.message ?? e), loading: false }))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return state
}
