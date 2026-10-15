import { useEffect, useState } from 'react'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { ReactFlow, Handle, MarkerType, Position, type Edge, type Node, type NodeProps } from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { api, useApi, type Impact } from '../api'
import { laneY } from '../elk'
import { cellPath } from '../nav'
import './impact.css'

const H = 56, LABEL_H = 24
const WIDTH: Record<string, number> = { start: 132, hop: 132, cell: 200, dependent: 150 }
const LANE_X = [0, 175, 350, 525, 715, 975]
type D = { kind: string; label: string; sublabel?: string }

function INode({ data }: NodeProps<Node<D>>) {
  return (
    <div className={`inode ${data.kind}`}>
      <Handle id="l" type="target" position={Position.Left} isConnectable={false} />
      <Handle id="t" type="target" position={Position.Top} isConnectable={false} />
      <Handle id="b" type="source" position={Position.Bottom} isConnectable={false} />
      {data.sublabel && <div className="k">{data.sublabel}</div>}
      <div className="l">{data.label}</div>
      <Handle id="r" type="source" position={Position.Right} isConnectable={false} />
    </div>
  )
}
const Lane = ({ data }: NodeProps<Node<{ label: string }>>) => <div className="lanelabel">{data.label}</div>
const nodeTypes = { inode: INode, lane: Lane }

async function build(d: Impact) {
  const y = await laneY(d.nodes.map(n => ({ id: n.uid, lane: n.lane, width: WIDTH[n.kind], height: H })), d.edges, 18)
  const nodes: Node[] = [
    ...d.lanes.map((label, i) => ({ id: 'lane' + i, type: 'lane', position: { x: LANE_X[i] ?? i * 180, y: 0 }, data: { label }, draggable: false, selectable: false, width: 120, height: LABEL_H })),
    ...d.nodes.map(n => ({
      id: n.uid, type: 'inode', position: { x: LANE_X[n.lane] ?? n.lane * 180, y: LABEL_H + 26 + (y.get(n.uid) ?? 0) },
      data: { kind: n.kind, label: n.label, sublabel: n.sublabel }, draggable: false, width: WIDTH[n.kind], height: H,
      sourcePosition: Position.Right, targetPosition: Position.Left,
    })),
  ]
  const laneOf = new Map(d.nodes.map(n => [n.uid, n.lane]))
  const edges: Edge[] = d.edges.map((e, i) => ({
    id: 'e' + i, source: e.src, target: e.dst,
    ...(laneOf.get(e.src) === laneOf.get(e.dst) ? { sourceHandle: 'b', targetHandle: 't' } : { sourceHandle: 'r', targetHandle: 'l' }),
    style: { stroke: '#2c6a3e', strokeWidth: 1.6 }, markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14, color: '#2c6a3e' },
  }))
  const height = Math.max(...d.nodes.map(n => LABEL_H + 26 + (y.get(n.uid) ?? 0))) + H + 12
  return { nodes, edges, height }
}

export default function ImpactGraph() {
  const { uid = '' } = useParams()
  const { search } = useLocation()
  const nav = useNavigate()
  const { data: d, error, loading } = useApi(() => api.impact(uid), [uid])
  const [flow, setFlow] = useState<Awaited<ReturnType<typeof build>>>()
  useEffect(() => { if (d) { let live = true; build(d).then(f => live && setFlow(f)); return () => { live = false } } }, [d])
  if (error) return <div className="state err">{error}</div>
  if (!d) return <div className="state">{loading ? 'Loading…' : ''}</div>
  const cells = new Set(d.impacted.map(i => i.cell_id))
  const st = d.stats
  return (
    <>
      <div className="imphead">
        <div>
          <div className="crumb"><Link to={`/explorer/impact${search}`}>Forward impact</Link> › starting element</div>
          <h1>{d.element.name}</h1>
        </div>
        <div className="istats" aria-label="Impact summary">
          <div><b>{st.templates}</b><span>templates</span></div><div><b>{st.cells}</b><span>pilot cells</span></div>
          <div><b>{st.entities}</b><span>{st.entities === 1 ? 'entity' : 'entities'}</span></div><div><b>{st.dependency_levels}</b><span>dependency levels</span></div>
        </div>
      </div>
      <div className="impbody">
        <div className="card impcanvas">
          <h2>Where it flows · source on the left, reported cells on the right</h2>
          <div className="flowwrap" style={{ height: flow?.height ?? 300 }}>
            {flow && (
              <ReactFlow nodes={flow.nodes} edges={flow.edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.02, maxZoom: 1.25 }}
                nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} panOnDrag={false} zoomOnScroll={false} zoomOnPinch={false}
                zoomOnDoubleClick={false} preventScrolling={false} minZoom={0.3}
                onNodeClick={(_, n) => { if (cells.has(n.id)) nav(cellPath(n.id)) }} />
            )}
          </div>
          <p className="impnote">Click any cell to open its reverse lineage (Stage 1) with the same date and entity.</p>
        </div>
        <aside className="card flush impacted">
          <h3>Impacted cells · {d.impacted.length}</h3>
          <p className="isub">Open a cell to see its reverse lineage; sizing is the next step.</p>
          <ul>
            {d.impacted.map(c => (
              <li key={c.cell_id}><div><b>{c.label}</b><small className="mono">{c.ref}</small></div><Link to={cellPath(c.cell_id)}>Reverse →</Link></li>
            ))}
          </ul>
        </aside>
      </div>
    </>
  )
}
