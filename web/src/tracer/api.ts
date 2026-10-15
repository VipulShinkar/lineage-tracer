// Client for docs/spec/tracer-api.md (base /api/tracer). VITE_USE_FIXTURES=true serves ./fixtures instead.
import { getRole } from '../api'
import { tracerFixture } from './fixtures'

export type SystemType = 'superset' | 'postgresql' | 'sqlite'
export type HopStatus = 'proven' | 'code_derived' | 'unresolved'
export type StepStatus = 'identified' | 'connection_required' | 'scanning' | 'unresolved' | 'failed'
export type Lane = 'system_of_record' | 'staging' | 'warehouse' | 'data_mart' | 'calc_engine' | 'reporting_layer' | 'report_tool'
export type Phase = 'connect' | 'locate_attribute' | 'identify_source' | 'identify_consumers'

export type Table = {
  column_labels?: Record<string, string>; default_row?: number; default_column?: string
  id: string; title: string; key_columns: string[]; value_columns: string[]; unit?: string
  rows: { index: number; key: Record<string, string>; values: Record<string, number | null> }[]
}
export type Report = {
  report_id: string; file_name: string
  meta: { title: string; return_type?: string; entity?: string; ref_date?: string; version?: string; delivered_to?: string; template?: string }
  tables: Table[]
}
export type Source = {
  type: SystemType; name?: string; url?: string; host?: string; database?: string; path?: string
  user?: string; password?: string; object?: string
}
export type Header = { direction: 'reverse'; template?: string; label: string; value: number | null; unit?: string | null; ref_date?: string }
export type Step = {
  n: number; system: string; system_type: SystemType; attribute_held_in: string[]; sourced_from: string[]
  sourced_from_is_sor?: boolean; consumed_by: string[]; status: StepStatus
}
export type Pending = { system: string; type: SystemType; host_hint?: string; database_hint?: string; phase: Phase; message: string }
export type Trace = {
  trace_id: string; status: 'running' | 'connection_required' | 'complete' | 'failed'; error?: string; header: Header
  stats: { systems_connected: number; sor_reached: number; sor_known: number; branches_outstanding: number }
  steps: Step[]; pending?: Pending
}
export type Connection = { system: string; type: SystemType; host?: string; database?: string; path?: string; user: string; password: string }
export type Hop = {
  n: number; status: HopStatus; from: string; to: string; attribute_held_in: string[]; sourced_from: string[]
  transformation: string; consumed_by: string; purpose?: string; business_rules?: string[]
  evidence: { code?: string; sql?: string; version?: string; log?: string; reconciliation?: string }
}
export type LineageData = {
  header: Header
  summary: { hops: number; proven: number; code_derived: number; unresolved: number; systems_of_record: number; title: string }
  lanes: Lane[]
  nodes: {
    id: string; system: string; object: string; lane: Lane; kind: 'sor' | 'intermediate' | 'anchor'
    service?: 'postgresql' | 'superset' | 'sqlite'; database?: string; schema?: string; name?: string
    on_value_path?: boolean; description?: string; entity_type?: 'table' | 'view' | 'chart' | 'file'; columns?: { name: string; data_type?: string; in_path: boolean; description?: string }[]
  }[]
  column_edges?: { from_node: string; from_column: string; to_node: string; to_column: string; hop: number; transformation?: string; kind?: 'value' | 'filter'; business_rule?: string }[]
  default_hop?: number
  edges: { from: string; to: string; hop: number; status: HopStatus }[]
  hops: Hop[]
}
export type Pack = { ref: string; sha256: string; download_url: string }

const USE_FIXTURES = import.meta.env.VITE_USE_FIXTURES === 'true'
const BASE = '/api/tracer'

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  if (USE_FIXTURES) return tracerFixture(method, path, body) as Promise<T>
  const isForm = body instanceof FormData
  const res = await fetch(BASE + path, {
    method,
    headers: { 'X-Role': getRole(), ...(body && !isForm ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? (isForm ? body : JSON.stringify(body)) : undefined,
  })
  if (!res.ok) {
    let detail = res.statusText
    try { const d = (await res.json()).detail; detail = typeof d === 'string' ? d : d ? JSON.stringify(d) : detail } catch { /* not json */ }
    throw new Error(detail)
  }
  return res.json()
}

/** Display name: drop the Postgres default schema. Ids stay intact. */
export const disp = (s?: string) => (s ?? '').replace(/(^|[^\w])public\./g, '$1')

export const tracer = {
  clearSystems: () => call<unknown>('DELETE', '/systems'),
  upload: (file: File) => { const f = new FormData(); f.append('file', file); return call<Report>('POST', '/reports', f) },
  start: (b: { report_id: string; mode?: 'datapoint' | 'report'; data_point: { table_id: string; row?: number; column?: string }; direction: 'reverse'; source: Source }) =>
    call<{ trace_id: string }>('POST', '/traces', b),
  trace: (id: string) => call<Trace>('GET', `/traces/${id}`),
  connect: (id: string, c: Connection) => call<{ ok: boolean }>('POST', `/traces/${id}/connections`, c),
  lineage: (id: string) => call<LineageData>('GET', `/traces/${id}/lineage`),
  pack: (id: string, format: 'pdf' | 'docx' = 'pdf') => call<Pack>('POST', `/traces/${id}/evidence-pack`, { format }),
}
