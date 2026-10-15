// OpenMetadata-style lineage canvas: table cards with column rows, column-to-column edges, column path highlighting.
// Focus mode (default) shows only the value path; join/filter columns are opt-in.
import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ReactFlow, Handle, Position, BaseEdge, EdgeLabelRenderer, getBezierPath,
  type Node, type Edge, type NodeProps, type EdgeProps, type ReactFlowInstance,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { layoutFree } from '../elk'
import './graph.css'
import { disp, type HopStatus, type LineageData } from './api'

type LNode = LineageData['nodes'][number]
type Col = { name: string; data_type?: string; in_path: boolean; description?: string }
export type NView = { id: string; service: string; db: string; name: string; type: string; cols: Col[]; node: LNode }
export type ColSel = { node: string; col: string }
export type CE = NonNullable<LineageData['column_edges']>[number]

const W = 280, HEAD = 62, ROW = 26, FOOT = 28, MIN_ZOOM = 0.7

/** Backend fields when present, else derived from system/object and the hops. */
export function views(l: LineageData): Map<string, NView> {
  const out = new Map<string, NView>()
  for (const n of l.nodes) {
    const parts = n.object.split('.')
    const name = n.name ?? parts[parts.length - 1]
    const schema = n.schema ?? (parts.length > 1 ? parts[parts.length - 2] : undefined)
    const db = [n.database ?? n.system, schema && schema !== 'public' ? schema : ''].filter(Boolean).join('.')
    let cols = n.columns
    if (!cols) {
      const names = new Set<string>()
      for (const h of l.hops) {
        if (h.to === n.id) h.attribute_held_in.forEach(a => names.add(a.split('.').pop()!))
        if (h.from === n.id) h.sourced_from.forEach(a => names.add(a.split('.').pop()!))
      }
      cols = [...names].map(x => ({ name: x, in_path: true }))
    }
    out.set(n.id, { id: n.id, service: n.service ?? 'postgresql', db, name, type: n.entity_type ?? (n.kind === 'anchor' ? 'chart' : 'table'), cols, node: n })
  }
  return out
}

export const ceKind = (c: CE) => c.kind ?? (/^join\/filter on/i.test(c.transformation ?? '') ? 'filter' : 'value')

/** Value-path model: backend flags when present, else derived (nodes reachable upstream from the anchor via value edges). */
export function valueModel(l: LineageData) {
  const ces = l.column_edges ?? []
  const valueEdge = (e: LineageData['edges'][number]) => {
    const mine = ces.filter(c => c.hop === e.hop && c.from_node === e.from && c.to_node === e.to)
    return mine.length === 0 || mine.some(c => ceKind(c) === 'value')
  }
  const flagged = l.nodes.some(n => n.on_value_path !== undefined)
  const keep = new Set<string>()
  if (flagged) l.nodes.forEach(n => n.on_value_path && keep.add(n.id))
  else {
    const q = l.nodes.filter(n => n.kind === 'anchor').map(n => n.id)
    q.forEach(x => keep.add(x))
    while (q.length) { const t = q.pop()!; for (const e of l.edges) if (e.to === t && valueEdge(e) && !keep.has(e.from)) { keep.add(e.from); q.push(e.from) } }
  }
  return { keep, valueEdge }
}

const Glyph = ({ s }: { s: string }) => (
  <svg width="24" height="24" viewBox="0 0 24 24" aria-hidden="true" className="g-glyph">
    {s === 'superset' ? <><rect x="2" y="2" width="20" height="20" rx="5" fill="#17a589" /><path d="M6 17V12M10.5 17V7M15 17v-6M19 17V9" stroke="#fff" strokeWidth="2" strokeLinecap="round" /></>
      : s === 'sqlite' ? <><rect x="2" y="2" width="20" height="20" rx="5" fill="#3b82a6" /><path d="M7 17c1-6 4-9 10-10-1 5-4 9-10 10Z" fill="#fff" /></>
      : <><rect x="2" y="2" width="20" height="20" rx="5" fill="#336791" /><path d="M7 15c-1-5 1-8 5-8s6 3 5 7c-.5 2-2 3-3 2M12 7c-2 2-2 6 0 9" stroke="#fff" strokeWidth="1.6" fill="none" strokeLinecap="round" /></>}
  </svg>
)

type ND = {
  v: NView; rows: Col[]; hidden: number; expanded: boolean; showCols: boolean; canToggle: boolean
  active?: Set<string>; selCol?: ColSel; selected: boolean
  onNode: (id: string) => void; onCol: (c: ColSel) => void; toggle: (id: string) => void
}
const nh = (rows: number, foot: boolean) => HEAD + rows * ROW + (foot ? FOOT : 0) + 6

function Card({ data: d }: NodeProps<Node<ND>>) {
  const v = d.v
  const dim = d.active && !d.rows.some(r => d.active!.has(v.id + '|' + r.name))
  return (
    <div className={`g-node ${v.node.kind === 'anchor' ? 'anchor' : ''} ${d.selected ? 'sel' : ''} ${dim ? 'dim' : ''}`}>
      <div className="g-head" onClick={() => d.onNode(v.id)}>
        <Handle id="t:" type="target" position={Position.Left} isConnectable={false} />
        <Glyph s={v.service} />
        <div className="g-title">
          <small>{disp(v.db)}</small>
          <b>{v.name}</b>
        </div>
        <span className="g-tag">{v.type === 'view' ? 'View' : v.type === 'chart' ? 'Chart' : v.type === 'file' ? 'File' : 'Table'}</span>
        <Handle id="s:" type="source" position={Position.Right} isConnectable={false} />
      </div>
      {d.showCols && d.rows.map(c => {
        const on = d.selCol?.node === v.id && d.selCol.col === c.name
        const off = d.active && !d.active.has(v.id + '|' + c.name)
        return (
          <div key={c.name} title={c.description} className={`g-row nodrag ${on ? 'on' : ''} ${off ? 'off' : ''} ${d.active?.has(v.id + '|' + c.name) ? 'act' : ''}`} onClick={e => { e.stopPropagation(); d.onCol({ node: v.id, col: c.name }) }}>
            <Handle id={'t:' + c.name} type="target" position={Position.Left} isConnectable={false} />
            <span className="mono">{c.name}</span><em>{c.data_type}</em>
            <Handle id={'s:' + c.name} type="source" position={Position.Right} isConnectable={false} />
          </div>
        )
      })}
      {d.showCols && d.canToggle && (
        <button className="g-more nodrag" onClick={e => { e.stopPropagation(); d.toggle(v.id) }}>
          {d.expanded ? 'Show fewer columns' : `+${d.hidden} more column${d.hidden === 1 ? '' : 's'}`}
        </button>
      )}
    </div>
  )
}

type ED = { hop: number; status: HopStatus; kind: 'tbl' | 'col' | 'flt'; sel: boolean; dim: boolean; hl: boolean; ce?: CE; tip?: string; rule?: string; pick: (hop: number, ce?: CE) => void }
function HopEdge(p: EdgeProps<Edge<ED>>) {
  const [path, lx, ly] = getBezierPath({ ...p, sourcePosition: Position.Right, targetPosition: Position.Left })
  const [over, setOver] = useState(false)
  const d = p.data!
  return (
    <g onMouseEnter={() => setOver(true)} onMouseLeave={() => setOver(false)}>
      <BaseEdge id={p.id} path={path} interactionWidth={14}
        className={`g-edge ${d.kind} ${d.status} ${d.sel ? 'sel' : ''} ${d.dim ? 'dim' : ''} ${d.hl ? 'hl' : ''}`} />
      <EdgeLabelRenderer>
        {d.kind === 'tbl' && (
          <button className={`t-hopdot ${d.status} ${d.sel ? 'sel' : ''} ${d.dim ? 'dim' : ''}`} style={{ transform: `translate(-50%,-50%) translate(${lx}px,${ly}px)` }}
            onClick={() => d.pick(d.hop)} aria-label={`Hop ${d.hop}`}>{d.hop}</button>
        )}
        {over && (d.rule || d.tip) && <div className="g-tip" style={{ transform: `translate(-50%,-120%) translate(${lx}px,${ly}px)` }}>{d.rule && <div className="rule">{d.rule}</div>}{d.tip && <div className="expr">{d.tip}</div>}</div>}
      </EdgeLabelRenderer>
    </g>
  )
}
const nodeTypes = { card: Card }
const edgeTypes = { hop: HopEdge }

/** Column keys and edge indexes on the full upstream + downstream path of one column. */
function trace(ces: { c: CE; i: number }[], s: ColSel) {
  const cols = new Set([s.node + '|' + s.col]), edges = new Set<number>()
  for (const dir of ['up', 'down'] as const) {
    const q = [s.node + '|' + s.col], seen = new Set(q)
    while (q.length) {
      const k = q.pop()!
      for (const { c, i } of ces) {
        const [a, b] = dir === 'up' ? [c.to_node + '|' + c.to_column, c.from_node + '|' + c.from_column] : [c.from_node + '|' + c.from_column, c.to_node + '|' + c.to_column]
        if (a !== k) continue
        edges.add(i); cols.add(b)
        if (!seen.has(b)) { seen.add(b); q.push(b) }
      }
    }
  }
  return { cols, edges }
}

export default function LineageGraph(p: {
  traceId: string; relayout: number; l: LineageData; showCols: boolean; showFilter: boolean; expandAll: number; collapseAll: number
  selHop?: number; selNode?: string; selCol?: ColSel
  onHop: (n: number, ce?: CE) => void; onNode: (id: string) => void; onCol: (c?: ColSel) => void; onReady: (rf: ReactFlowInstance) => void
}) {
  const { l, showCols, showFilter } = p
  const vs = useMemo(() => views(l), [l])
  const model = useMemo(() => valueModel(l), [l])
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [pos, setPos] = useState<Map<string, { x: number; y: number }>>(new Map())
  const rf = useRef<ReactFlowInstance>(null)
  const wrap = useRef<HTMLDivElement>(null)
  const fitKey = useRef('')
  const storeKey = `tracer.pos.${p.traceId}`
  const [moved, setMoved] = useState<Map<string, { x: number; y: number }>>(() => {
    try { return new Map(Object.entries(JSON.parse(localStorage.getItem(storeKey) ?? '{}'))) } catch { return new Map() }
  })
  useEffect(() => {
    if (!p.relayout) return
    setMoved(new Map()); fitKey.current = ''
    try { localStorage.removeItem(storeKey) } catch { /* storage unavailable */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.relayout])
  useEffect(() => { if (p.expandAll) setExpanded(new Set(l.nodes.map(n => n.id))) }, [p.expandAll, l])
  useEffect(() => { if (p.collapseAll) setExpanded(new Set()) }, [p.collapseAll])

  // visible subset
  const vis = useMemo(() => {
    const ids = new Set(showFilter ? l.nodes.map(n => n.id) : [...model.keep])
    const edges = l.edges.filter(e => ids.has(e.from) && ids.has(e.to) && (showFilter || model.valueEdge(e)))
    const ces = (l.column_edges ?? []).map((c, i) => ({ c, i })).filter(({ c }) => ids.has(c.from_node) && ids.has(c.to_node) && (showFilter || ceKind(c) === 'value'))
    const used = new Map<string, Set<string>>()
    for (const { c } of ces) {
      (used.get(c.from_node) ?? used.set(c.from_node, new Set()).get(c.from_node)!).add(c.from_column);
      (used.get(c.to_node) ?? used.set(c.to_node, new Set()).get(c.to_node)!).add(c.to_column)
    }
    return { ids, edges, ces, used }
  }, [l, model, showFilter])

  const rowsOf = (v: NView) => {
    const u = vis.used.get(v.id)
    const base = u && u.size ? v.cols.filter(c => u.has(c.name)) : v.cols.filter(c => c.in_path)
    const exp = expanded.has(v.id)
    return { rows: exp ? v.cols : base, hidden: v.cols.length - base.length, exp, canToggle: v.cols.length > base.length }
  }
  const visNodes = [...vs.values()].filter(v => vis.ids.has(v.id))
  const sig = visNodes.map(v => { const r = rowsOf(v); return v.id + r.rows.length + r.canToggle }).join() + showCols + showFilter

  async function fit() {
    const inst = rf.current, box = wrap.current
    if (!inst || !box) return
    await inst.fitView({ padding: 0.05 })
    const z = inst.getViewport().zoom
    if (z >= MIN_ZOOM) return
    const a = visNodes.find(v => v.node.kind === 'anchor') ?? visNodes[visNodes.length - 1]
    const ap = a && pos.get(a.id)
    if (!ap) return
    inst.setViewport({ zoom: MIN_ZOOM, x: box.clientWidth - (ap.x + W) * MIN_ZOOM - 24, y: box.clientHeight / 2 - (ap.y + 80) * MIN_ZOOM })
  }

  useEffect(() => {
    let live = true
    layoutFree(visNodes.map(v => { const r = rowsOf(v); return { id: v.id, width: W, height: showCols ? nh(r.rows.length, r.canToggle) : HEAD + 6 } }),
      vis.edges.map(e => ({ src: e.from, dst: e.to }))).then(m => { if (live) setPos(m) })
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sig, l])
  useEffect(() => {
    const k = `${showFilter}|${showCols}|${l.summary.title}|${p.relayout}`
    if (pos.size && fitKey.current !== k) { fitKey.current = k; setTimeout(fit, 150) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pos])

  const hl = useMemo(() => (p.selCol ? trace(vis.ces, p.selCol) : undefined), [p.selCol, vis])
  const toggle = (id: string) => setExpanded(s => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })

  const nodes: Node[] = visNodes.filter(v => pos.has(v.id)).map(v => {
    const r = rowsOf(v)
    return {
      id: v.id, type: 'card', position: moved.get(v.id) ?? pos.get(v.id)!, draggable: true, measured: { width: W, height: showCols ? nh(r.rows.length, r.canToggle) : HEAD + 6 }, width: W, height: showCols ? nh(r.rows.length, r.canToggle) : HEAD + 6,
      data: { v, rows: r.rows, hidden: r.hidden, expanded: r.exp, showCols, canToggle: r.canToggle, active: hl?.cols, selCol: p.selCol, selected: p.selNode === v.id, onNode: p.onNode, onCol: p.onCol, toggle } satisfies ND,
    }
  })

  const edges: Edge[] = useMemo(() => {
    const out: Edge[] = []
    const shown = (id: string, c: string) => showCols && (expanded.has(id) || vis.used.get(id)?.has(c))
    const pick = (hop: number, ce?: CE) => p.onHop(hop, ce)
    const hopTx = (n: number) => l.hops.find(h => h.n === n)?.transformation
    for (const e of vis.edges) {
      const mine = vis.ces.filter(({ c }) => c.hop === e.hop && c.from_node === e.from && c.to_node === e.to)
      if (showCols && mine.length) {
        for (const { c, i } of mine) {
          out.push({
            id: `c${i}`, source: e.from, target: e.to, type: 'hop',
            sourceHandle: 's:' + (shown(e.from, c.from_column) ? c.from_column : ''), targetHandle: 't:' + (shown(e.to, c.to_column) ? c.to_column : ''),
            data: { hop: e.hop, status: e.status, kind: ceKind(c) === 'filter' ? 'flt' : 'col', sel: p.selHop === e.hop, dim: !!hl && !hl.edges.has(i), hl: !!hl?.edges.has(i), ce: c, tip: c.transformation, rule: c.business_rule, pick } satisfies ED,
          })
        }
      } else {
        out.push({ id: `e${e.hop}`, source: e.from, target: e.to, type: 'hop', sourceHandle: 's:', targetHandle: 't:',
          data: { hop: e.hop, status: e.status, kind: 'tbl', sel: p.selHop === e.hop, dim: !!hl, hl: false, tip: hopTx(e.hop), pick } satisfies ED })
      }
    }
    return out
  }, [l, vis, showCols, expanded, hl, p.selHop, vs, p.onHop])

  return (
    <div ref={wrap} style={{ height: '100%' }}>
      <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} nodesDraggable nodesConnectable={false}
        onNodeDrag={(_, n) => setMoved(m => new Map(m).set(n.id, { x: n.position.x, y: n.position.y }))}
        onNodeDragStop={(_, n) => setMoved(m => { const x = new Map(m).set(n.id, { x: n.position.x, y: n.position.y }); try { localStorage.setItem(storeKey, JSON.stringify(Object.fromEntries(x))) } catch { /* ignore */ } return x })} elementsSelectable={false}
        minZoom={0.2} maxZoom={1.6} onInit={i => { rf.current = i; p.onReady(i) }} onPaneClick={() => p.onCol(undefined)}
        onEdgeClick={(_, e) => { const d = e.data as ED; p.onHop(d.hop, d.ce) }} />
    </div>
  )
}
