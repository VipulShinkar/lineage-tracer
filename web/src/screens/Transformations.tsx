import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api, useApi, type MappingView } from '../api'
import { dates, n1 } from '../format'
import { cellPath } from '../nav'
import './transformations.css'

const bold = (t: string) => t.split(/(C \d\d\.\d\d)/).map((s, i) => (i % 2 ? <b key={i}>{s}</b> : s))

export default function Transformations() {
  const { cellId = '' } = useParams()
  const { data: d, error, loading } = useApi(() => api.transformations(cellId), [cellId])
  const [compared, setCompared] = useState<MappingView>()
  const [busy, setBusy] = useState(false)
  if (error) return <div className="state err">{error}</div>
  if (!d) return <div className="state">{loading ? 'Loading…' : ''}</div>
  const m = compared ?? d.mapping
  const toggle = async () => {
    if (compared) return setCompared(undefined)
    setBusy(true)
    try { setCompared(await api.mapping(d.mapping.uid, d.mapping.version, d.mapping.previous_version, cellId)) } finally { setBusy(false) }
  }
  return (
    <div className="cellbody tx">
      <section>
        <div className="txhead">
          <h2>{d.transformations.length} transformations on the journey, in order</h2>
          <span>Versions shown are those in force on {dates(d.as_of)}</span>
        </div>
        <div className="txgrid">
          {d.transformations.map(t => (
            <article key={t.id} className={`card txcard ${t.manual ? 'manual' : ''}`}>
              <header>
                <span className="tid">{t.id}</span><span className="ttype">{t.type}</span><span className="thop">{t.hop}</span>
                <span className={`amt mono ${t.amount < 0 ? 'neg' : ''}`}>{n1(t.amount)}</span>
              </header>
              <p>{t.description}</p>
              <footer>
                {t.version && <span>{t.version}{t.effective_from ? ` · eff. ${dates(t.effective_from)}` : ''}</span>}
                <span>{t.owner}</span>
                {t.approved_on && <span>Approved {dates(t.approved_on)}</span>}
                {t.manual
                  ? <Link to={cellPath(cellId, 'waterfall')}>{t.reference.label}</Link>
                  : t.reference.url ? <a href={t.reference.url}>{t.reference.label}</a> : <span className="ref">{t.reference.label}</span>}
              </footer>
            </article>
          ))}
        </div>
      </section>

      <aside>
        <div className="card flush">
          <div className="mhead">
            <h3>Mapping used by T4 · {m.name}</h3>
            <small>Version {m.version} · effective {dates(m.effective_from)} · rows relevant to this cell</small>
          </div>
          <table className="maptable">
            <tbody>
              {m.rows.map(r => (
                <tr key={r.code} className={r.changed && compared ? 'changed' : ''}>
                  <td className="mono">{r.code}</td><td>{r.label}{r.changed && compared && <span className="chg"> · changed vs {m.previous_version}</span>}</td>
                  <td className="tgt">{r.target}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {m.previous_version && (
            <div className="mfoot">
              {compared ? <>Comparing with version {m.previous_version}: {m.rows.filter(r => r.changed).length} changed rows · </> : <>Previous version {m.previous_version} differs in {m.differs_in} rows · </>}
              <button className="linkbtn" onClick={toggle} disabled={busy}>{compared ? 'hide comparison' : 'compare'}</button>
            </div>
          )}
        </div>
        <div className="card dep">
          <h3>Cell-to-cell dependency</h3>
          <p>{bold(d.dependency.text)}</p>
          <div className="formula mono">{d.dependency.formula}</div>
        </div>
      </aside>
    </div>
  )
}
