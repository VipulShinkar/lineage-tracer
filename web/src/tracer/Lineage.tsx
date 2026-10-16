import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import type { ReactFlowInstance } from '@xyflow/react'
import LineageGraph, { views, type CE, type ColSel } from './LineageGraph'
import { api, saveBlob, useApi } from '../api'
import { dates } from '../format'
import { DEMO } from './demo'
import { disp, tracer, type Hop, type HopStatus, type LineageData } from './api'

const STATUS: Record<HopStatus, string> = { proven: 'Proven', code_derived: 'Code-derived', unresolved: 'Unresolved' }

const List = ({ v }: { v: string[] }) => <p className="mono-l">{v.length ? disp(v.join(', ')) : '—'}</p>

function Panel({ hop, l, ce }: { hop: Hop; l: LineageData; ce?: CE }) {
  const [sql, setSql] = useState(false)
  useEffect(() => setSql(false), [hop.n])
  const name = (s: string) => disp(l.nodes.find(n => n.id === s)?.object ?? s)
  const ev = hop.evidence
  const rows: [string, string | undefined][] = [['Code', ev.code], ['Version', ev.version], ['Log', ev.log], ['Reconciliation', ev.reconciliation]]
  return (
    <aside className="t-card t-panel">
      <div className="t-ph"><span className="t-eyebrow">Hop {hop.n}</span><span className={`t-pill ${hop.status}`}>{STATUS[hop.status]}</span></div>
      <h3 className="t-ft mono">{name(hop.from)} → {name(hop.to)}</h3>
      {(hop.purpose || hop.business_rules?.length) && (
        <section className="t-biz">
          <h4>Business logic</h4>
          {hop.purpose && <p>{hop.purpose}</p>}
          {!!hop.business_rules?.length && <ul>{hop.business_rules.map((r, i) => <li key={i}>{r}</li>)}</ul>}
        </section>
      )}
      {ce && <p className="t-colline mono">{ce.from_column} → {ce.to_column}{ce.transformation ? <><br /><span>{ce.transformation}</span></> : null}</p>}
      <h4>Attribute held in</h4><List v={hop.attribute_held_in} />
      <h4>Sourced from</h4><List v={hop.sourced_from} />
      <h4>Transformation</h4><p>{disp(hop.transformation) || '—'}</p>
      <h4>Consumed by</h4><p className="mono-l">{disp(hop.consumed_by) || '—'}</p>
      <hr />
      <h4>Evidence</h4>
      <dl className="t-ev">
        {rows.filter(([, v]) => v).map(([k, v]) => <div key={k}><dt>{k}</dt><dd className="mono">{disp(dates(v))}</dd></div>)}
      </dl>
      {ev.sql && (
        <>
          <button className="t-link" onClick={() => setSql(s => !s)} aria-expanded={sql}>{sql ? 'Hide SQL' : 'Show SQL'}</button>
          {sql && <pre className="t-sql">{ev.sql}</pre>}
        </>
      )}
    </aside>
  )
}

function NodePanel({ id, l }: { id: string; l: LineageData }) {
  const v = views(l).get(id)
  if (!v) return null
  const writers = l.hops.filter(h => h.to === id)
  return (
    <aside className="t-card t-panel">
      <div className="t-ph"><span className="t-eyebrow">{v.type}</span><span className="t-pill">{v.service}</span></div>
      <h3 className="t-ft mono">{disp(v.db)}.{v.name}</h3>
      {v.node.description && <p className="t-desc">{v.node.description}</p>}
      <h4>Columns</h4>
      <ul className="t-cols-l">
        {v.cols.map(c => <li key={c.name} className={c.in_path ? 'in' : ''} title={c.description}><span className="mono">{c.name}</span><em>{c.data_type}</em>{c.description && <small>{c.description}</small>}</li>)}
        {!v.cols.length && <li>—</li>}
      </ul>
      <h4>Written by</h4>
      {writers.length ? writers.map(h => (
        <p key={h.n} className="mono-l">Hop {h.n} · {disp(h.evidence.code) || h.transformation} <span className={`t-pill ${h.status}`}>{STATUS[h.status]}</span></p>
      )) : <p>Nothing within the traced path writes this object (source).</p>}
    </aside>
  )
}

export default function Lineage() {
  const { id = '' } = useParams()
  const { data: l, error } = useApi(() => tracer.lineage(id), [id])
  const [sel, setSel] = useState<{ hop?: number; node?: string; ce?: CE }>({})
  const [col, setCol] = useState<ColSel>()
  const [showCols, setShowCols] = useState(true)
  const [showFilter, setShowFilter] = useState(false)
  const [relayout, setRelayout] = useState(0)
  const [expandAll, setExpandAll] = useState(0)
  const [collapseAll, setCollapseAll] = useState(0)
  const [rf, setRf] = useState<ReactFlowInstance>()
  const [busy, setBusy] = useState(false)
  const [xerr, setXerr] = useState<string>()

  useEffect(() => {
    if (!l) return
    const anchor = l.nodes.find(n => n.kind === 'anchor')?.id
    setSel({ hop: l.default_hop ?? l.edges.filter(e => e.to === anchor).sort((a, b) => b.hop - a.hop)[0]?.hop ?? l.hops[0]?.n })
  }, [l])
  const onHop = useCallback((n: number, ce?: CE) => setSel({ hop: n, ce }), [])
  const onNode = useCallback((nid: string) => setSel({ node: nid }), [])

  if (error) return <div className="state err">{error}</div>
  if (!l) return <div className="state">Loading…</div>
  const s = l.summary
  const sub = ['Reverse', l.header.label, l.header.ref_date ? dates(l.header.ref_date) : '', `${s.hops} hops`, `${s.proven} proven`, `${s.code_derived} code-derived`, `${s.unresolved} unresolved`].filter(Boolean).join(' · ')
  const hop = l.hops.find(h => h.n === sel.hop)
  const anchor = l.nodes.find(n => n.kind === 'anchor')
  const anchorCols = (anchor && views(l).get(anchor.id)?.cols) || []

  async function exportPack() {
    setBusy(true); setXerr(undefined)
    try {
      const p = await tracer.pack(id, 'pdf')
      saveBlob(await (DEMO ? fetch(p.download_url).then(r => r.blob()) : api.download(p.download_url)), `${p.ref}.pdf`)
    } catch (e) { setXerr((e as Error).message) } finally { setBusy(false) }
  }

  return (
    <main className="t-main wide">
      <div className="t-titlerow">
        <div>
          <h1 className="t-h1">{s.title}</h1>
          <p className="t-subm mono">{sub}</p>
        </div>
        <div className="t-actions">
          {DEMO ? <Link to="/" className="t-textbtn">All snapshot traces</Link> : <Link to="/" className="t-textbtn">New trace</Link>}
          <button className="t-btn" onClick={exportPack} disabled={busy}>{busy ? 'Exporting…' : 'Export evidence pack'}</button>
        </div>
      </div>
      {xerr && <p className="t-err t-banner" role="alert">{xerr}</p>}
      <div className="t-lin">
        <section className="t-card t-graph">
          <div className="t-toolbar">
            <button onClick={() => rf?.fitView({ padding: 0.06, duration: 200 })}>Fit</button>
            <button onClick={() => rf?.zoomIn({ duration: 150 })} aria-label="Zoom in">+</button>
            <button onClick={() => rf?.zoomOut({ duration: 150 })} aria-label="Zoom out">−</button>
            <span className="sep" />
            <button onClick={() => setExpandAll(x => x + 1)}>Expand all</button>
            <button onClick={() => setCollapseAll(x => x + 1)}>Collapse all</button>
            <button onClick={() => { setRelayout(x => x + 1); setCol(undefined) }} title="Reset node positions">Re-layout</button>
            {l.header.value == null && anchorCols.length > 0 && (
              <label className="t-pick">Trace column:
                <select value={col?.node === anchor?.id ? col?.col ?? '' : ''} onChange={e => setCol(e.target.value && anchor ? { node: anchor.id, col: e.target.value } : undefined)}>
                  <option value="">(none)</option>
                  {anchorCols.map(c => <option key={c.name} value={c.name}>{c.name}</option>)}
                </select>
              </label>
            )}
            <label className="t-switch"><input type="checkbox" checked={showCols} onChange={e => { setShowCols(e.target.checked); setCol(undefined) }} />Column lineage</label>
            <label className="t-switch"><input type="checkbox" checked={showFilter} onChange={e => { setShowFilter(e.target.checked); setCol(undefined) }} />Show join/filter columns</label>
          </div>
          <div className="t-flow">
            <LineageGraph traceId={id} relayout={relayout} l={l} showCols={showCols} showFilter={showFilter} expandAll={expandAll} collapseAll={collapseAll} selHop={sel.hop} selNode={sel.node} selCol={col}
              onHop={onHop} onNode={onNode} onCol={c => setCol(c)} onReady={setRf} />
          </div>
          <div className="t-legend">
            <span><i className="proven" />Proven: logic identified and reconciled to data</span>
            <span><i className="code_derived" />Code-derived: logic identified, not reconciled</span>
            {s.unresolved > 0 && <span><i className="unresolved" />Unresolved: source not found</span>}
            <span className="faint">Click a column to trace its path, an edge for hop detail, a table for its columns.</span>
          </div>
        </section>
        {sel.node ? <NodePanel id={sel.node} l={l} /> : hop && <Panel hop={hop} l={l} ce={sel.ce} />}
      </div>
    </main>
  )
}
