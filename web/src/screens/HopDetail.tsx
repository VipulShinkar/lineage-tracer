import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, useApi } from '../api'
import { dates, int } from '../format'
import { cellPath } from '../nav'
import './hop.css'

export default function HopDetail() {
  const { cellId = '', n = '3' } = useParams()
  const nav = useNavigate()
  const [only, setOnly] = useState(true)
  const { data: d, error, loading } = useApi(() => api.hop(cellId, Number(n)), [cellId, n])
  if (error) return <div className="state err">{error}</div>
  if (!d) return <div className="state">{loading ? 'Loading…' : ''}</div>
  const h = d.hop
  const rows: [string, string][] = [
    ['Mechanism', h.mechanism], ['Frequency', h.frequency], ['Cut-off', dates(h.cutoff)],
    ['Actual run', dates(h.actual_run)], ['Run ID', h.run_id], ['Re-run', h.rerun ? 'Yes' : 'No'],
  ]
  return (
    <div className="cellbody hopdetail">
      <div className="card pathbar">
        <span className="plabel">Path</span>
        <div className="chips" role="group" aria-label="Hops">
          {d.path.map(p => (
            <button key={p.n} className={`pchip ${p.manual ? 'manual' : ''} ${p.n === h.n ? 'cur' : ''} ${only && p.n !== h.n ? 'dim' : ''}`}
              aria-current={p.n === h.n ? 'step' : undefined} onClick={() => nav(cellPath(cellId, `hop/${p.n}`))}>
              <b>{p.n}</b> {p.label}
            </button>
          ))}
        </div>
        <label className="only"><input type="checkbox" checked={only} onChange={e => setOnly(e.target.checked)} />Highlight this path only</label>
      </div>

      <div className="row3">
        <div className="card">
          <div className="eyebrow">Hop {h.n} · how it was sourced</div>
          <h2 className="hopttl">{h.from} → {h.to}</h2>
          <dl className="kv">{rows.map(([k, v]) => <div key={k} style={{ display: 'contents' }}><dt>{k}</dt><dd className={k === 'Run ID' ? 'mono' : ''}>{v}</dd></div>)}</dl>
        </div>
        <div className="card">
          <div className="eyebrow">Records and value through this hop</div>
          <div className="inout">
            <div><span>Records in</span><b>{int(d.records.in)}</b></div>
            <span className="arr" aria-hidden="true">⟶</span>
            <div><span>Records out</span><b>{int(d.records.out)}</b></div>
          </div>
          <p className="note">{dates(d.records.note)}</p>
          <Link to={cellPath(cellId, 'waterfall')} className="wflink">See this step in the value waterfall →</Link>
        </div>
        <div className="card">
          <div className="eyebrow">Ownership</div>
          <dl className="kv own">
            <dt>Data owner</dt><dd>{d.ownership.data_owner}</dd>
            <dt>System owner</dt><dd>{d.ownership.system_owner}</dd>
            <dt>Certified</dt><dd>{dates(d.ownership.certified)}</dd>
            <dt>Open DQ issues</dt><dd>{d.ownership.open_dq_issues}</dd>
          </dl>
        </div>
      </div>

      <div className="row2">
        <div className="card flush">
          <h3 className="ptitle">Attribute-level mapping at this hop</h3>
          <table className="mtable">
            <thead><tr><th>Source field</th><th>Target field</th><th>What happens</th></tr></thead>
            <tbody>
              {d.mappings.map((m, i) => (
                <tr key={i}><td className="mono">{m.source_field}</td><td className="mono">{m.target_field}</td><td>{m.what_happens}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card flush">
          <h3 className="ptitle">Controls at this hop · 30-Jun-2026 run</h3>
          <ul className="ctl">
            {d.controls.map(c => (
              <li key={c.id}>
                <span className={`badge ${c.status}`}>{c.status.toUpperCase()}</span>
                <div><b>{c.name}</b><small>{c.detail}</small></div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
