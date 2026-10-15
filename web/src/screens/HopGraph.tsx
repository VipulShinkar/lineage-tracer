import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  ReactFlow, Handle, Position, BaseEdge, EdgeLabelRenderer, getBezierPath, MarkerType,
  type Node, type Edge, type NodeProps, type EdgeProps,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { laneY } from '../elk'
import { api, useApi, type Level, type Lineage } from '../api'
import { dates, n1 } from '../format'
import { cellPath } from '../nav'
import './graph.css'

const W = 134, H = 58, COL = 180, LANE_H = 24

type NodeData = { kind: string; label: string; sublabel?: string }
const KIND_LABEL: Record<string, string> = { source: 'SOURCE', reference: 'REFERENCE', gap: 'GAP', dataset: 'DATASET', field: 'ATTRIBUTE', manual: 'MANUAL', calc: 'CALC', anchor: 'ANCHOR' }

function Box({ data }: NodeProps<Node<NodeData>>) {
  return (
    <div className={`gnode ${data.kind}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <div className="k">{data.kind === 'manual' ? (!data.sublabel ? 'MANUAL' : /^MANUAL/i.test(data.sublabel) ? data.sublabel : `MANUAL · ${data.sublabel}`) : (KIND_LABEL[data.kind] ?? data.kind)}</div>
      <div className="l">{data.label.replace(/_/g, "_​")}</div>
      {data.kind !== 'manual' && data.kind !== 'anchor' && data.sublabel && <div className="s">{data.sublabel}</div>}
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  )
}
const LaneLabel = ({ data }: NodeProps<Node<{ label: string }>>) => <div className="lanelabel">{data.label}</div>

type EdgeData = { hop?: number; dashed?: boolean; badge: boolean; go: (n: number) => void }
function HopEdge(p: EdgeProps<Edge<EdgeData>>) {
  const [path] = getBezierPath({ ...p, sourcePosition: Position.Right, targetPosition: Position.Left })
  const d = p.data!
  return (
    <>
      <BaseEdge id={p.id} path={path} markerEnd={p.markerEnd}
        style={{ stroke: d.dashed ? 'var(--red)' : '#7c828c', strokeWidth: 1.6, strokeDasharray: d.dashed ? '5 4' : undefined }} />
      {d.badge && d.hop && (
        <EdgeLabelRenderer>
          <button className="hopbadge nodrag nopan" style={{ transform: `translate(-50%,-50%) translate(${p.targetX - 28}px,${p.targetY}px)` }}
            onClick={() => d.go(d.hop!)} aria-label={`Hop ${d.hop}: open hop detail`}>{d.hop}</button>
        </EdgeLabelRenderer>
      )}
    </>
  )
}
const nodeTypes = { box: Box, lane: LaneLabel }
const edgeTypes = { hop: HopEdge }

async function layout(l: Lineage, go: (n: number) => void) {
  const y = await laneY(l.nodes.map(n => ({ id: n.uid, lane: n.lane, width: W, height: H })), l.edges)
  const nodes: Node[] = [
    ...l.lanes.map((label, i) => ({ id: 'lane' + i, type: 'lane', position: { x: i * COL, y: 0 }, data: { label }, draggable: false, selectable: false, width: W, height: LANE_H })),
    ...l.nodes.map(n => ({
      id: n.uid, type: 'box', position: { x: n.lane * COL, y: LANE_H + 36 + (y.get(n.uid) ?? 0) },
      data: { kind: n.kind, label: n.label, sublabel: n.sublabel }, draggable: false, width: W, height: H,
    })),
  ]
  const seen = new Set<number>()
  const edges: Edge[] = l.edges.map((e, i) => {
    const badge = !!e.hop && !seen.has(e.hop)
    if (e.hop) seen.add(e.hop)
    return {
      id: 'e' + i, source: e.src, target: e.dst, type: 'hop', data: { hop: e.hop, dashed: e.dashed, badge, go },
      markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: e.dashed ? '#9b2c22' : '#7c828c' },
    }
  })
  const height = Math.max(...l.nodes.map(n => LANE_H + 36 + (y.get(n.uid) ?? 0))) + H + 16
  return { nodes, edges, height }
}

const LEVELS: [Level, string][] = [['system', 'System'], ['dataset', 'Dataset'], ['attribute', 'Attribute']]

export default function HopGraph() {
  const { cellId = '' } = useParams()
  const nav = useNavigate()
  const [level, setLevel] = useState<Level>('dataset')
  const { data, error, loading } = useApi(() => api.lineage(cellId, level), [cellId, level])
  const [flow, setFlow] = useState<{ nodes: Node[]; edges: Edge[]; height: number }>()
  const go = useMemo(() => (n: number) => nav(cellPath(cellId, `hop/${n}`)), [cellId, nav])
  useEffect(() => {
    if (!data) return
    let live = true
    layout(data, go).then(f => live && setFlow(f))
    return () => { live = false }
  }, [data, go])

  const s = data?.summary
  return (
    <div className="cellbody hopgraph">
      <div className="leftcol">
        {s && (
          <div className="card summary">
            <div className="eyebrow">Lineage summary</div>
            <dl>
              <dt>Hops to submission</dt><dd>{s.hops}</dd>
              <dt>First-hop systems</dt><dd>{s.first_hop_systems}</dd>
              <dt>Transformations</dt><dd>{s.transformations}</dd>
              <dt>Manual adjustments</dt><dd className="neg">{s.manual_adjustments}</dd>
              <dt>Controls</dt><dd>{s.controls}</dd>
              <dt>Unexplained residual</dt><dd>{n1(s.unexplained_residual)}</dd>
            </dl>
          </div>
        )}
        {data?.known_gaps.map(g => (
          <div className="card gapcard" key={g.uid}>
            <h3>Known gap · {g.status}</h3>
            <p>{g.description}</p>
            <small>Owner: {g.owner} · target {dates(g.target_date)}</small>
          </div>
        ))}
        {data && (
          <div className="card">
            <h3>Cell dependencies</h3>
            <p className="depline">{data.cell_dependencies}</p>
          </div>
        )}
      </div>

      <div className="card canvas">
        <div className="chead">
          <h2>Where this number came from</h2>
          <div className="seg" role="group" aria-label="Detail level">
            {LEVELS.map(([v, t]) => <button key={v} className={level === v ? 'on' : ''} aria-pressed={level === v} onClick={() => setLevel(v)}>{t}</button>)}
          </div>
        </div>
        {error && <div className="state err">{error}</div>}
        {loading && !flow && <div className="state">Loading…</div>}
        <div className="flowwrap" style={{ height: flow?.height ?? 300 }}>
          {flow && (
            <ReactFlow nodes={flow.nodes} edges={flow.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} fitView fitViewOptions={{ padding: 0.02, maxZoom: 1.25 }}
              nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} panOnDrag={false} zoomOnScroll={false} zoomOnPinch={false}
              zoomOnDoubleClick={false} preventScrolling={false} minZoom={0.3} />
          )}
        </div>
        <div className="glegend">
          <span>Numbered circles = hops · click one to see how it was sourced</span>
          <span className="o">Orange = manual / EUC</span>
          <span className="r">Dashed red = gap</span>
        </div>
      </div>
    </div>
  )
}
