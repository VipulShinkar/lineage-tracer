import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { api, saveBlob, useApi } from '../api'
import { d1, n1, n2 } from '../format'
import { impactPath } from '../nav'
import './impact.css'

const LABEL = { within: 'Within', near: 'Near threshold', above: 'Above threshold' }

export default function Sizing() {
  const { uid = '' } = useParams()
  const { search } = useLocation()
  const sp = new URLSearchParams(search)
  const ref = sp.get('ref') ?? 'INC-[NUMBER]'
  const reason = sp.get('reason') ?? 'dq_incident'
  const [pct, setPct] = useState(15)
  const [debounced, setDebounced] = useState(15)
  const [toast, setToast] = useState<string>()
  useEffect(() => { const t = setTimeout(() => setDebounced(pct), 250); return () => clearTimeout(t) }, [pct])
  // keep the previous result on screen while a new one loads (no flicker while dragging)
  const [last, setLast] = useState<Awaited<ReturnType<typeof api.whatIf>>>()
  const { data, error } = useApi(() => api.whatIf(uid, debounced, ref, reason), [uid, debounced])
  useEffect(() => { if (data) setLast(data) }, [data])
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(undefined), 2600); return () => clearTimeout(t) } }, [toast])
  const d = data ?? last
  const name = uid.split(/[.:]/).pop() ?? uid

  const exportReport = async () => {
    try { saveBlob(await api.impactReport(uid, pct, ref), `impact-report-${name}-${pct}pct.pdf`) } catch (e) { setToast((e as Error).message) }
  }
  return (
    <main className="main sizing">
      <section>
        <div className="crumb"><Link to={impactPath(uid, false, search)}>Impact of {name}</Link> › sizing</div>
        <h1>How big is the impact, and do we need to resubmit?</h1>

        <div className="card whatif">
          <div className="txt">
            <h3>What-if: apply the missing haircut to affected collateral</h3>
            <p>Collateral loaded 28–30 Jun without haircut. Estimate propagates through recorded rules T7 → C 02.00 → C 03.00.</p>
          </div>
          <label className="hl" htmlFor="hc">Haircut</label>
          <input id="hc" className="slider" type="range" min={0} max={50} step={1} value={pct} onChange={e => setPct(+e.target.value)} aria-valuetext={`${pct} percent`} />
          <output className="pctbig" htmlFor="hc">{pct}%</output>
        </div>

        {error && <div className="state err">{error}</div>}
        {d && (
          <>
            <div className="card flush">
              <table className="stab">
                <thead><tr><th>Impacted cell</th><th>Reported</th><th>From this element</th><th>Estimated</th><th>Change</th><th>% of cell</th><th>Threshold (1% cell)</th></tr></thead>
                <tbody>
                  {d.rows.map(r => (
                    <tr key={r.cell_id}>
                      <td><b>{r.label}</b><small>{r.ref}</small></td>
                      <td className="mono">{n1(r.reported)}</td><td className="mono from">{n1(r.from_element)}</td>
                      <td className="mono est">{n1(r.estimated)}</td><td className="mono chg">{d1(r.change)}</td>
                      <td className="mono">{n2(r.pct_of_cell)}%</td>
                      <td><span className={`tbadge ${r.threshold}`}>{LABEL[r.threshold]}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="smethod">{d.method_note}</p>
          </>
        )}
      </section>

      <aside className="sside">
        {d && (
          <>
            <div className="card ratio">
              <div className="lbl">{d.ratio.label}</div>
              <div className="big">{n2(d.ratio.estimated_pct)}%<small>from {n2(d.ratio.reported_pct)}%</small></div>
              <div className="bps">{n1(d.ratio.change_bps)} bps</div>
              <div className="thr">Ratio threshold for resubmission: {d.ratio.threshold_bps} bps</div>
            </div>
            <div className={`decision ${d.decision.level}`} role="status">
              <h3>{d.decision.title}</h3><p>{d.decision.text}</p>
            </div>
            <div className="card actions">
              <button className="btn" onClick={exportReport}>Export impact report</button>
              <div className="two">
                <button className="ghost" onClick={() => setToast(`Linked to ${ref}`)}>Link to {ref}</button>
                <button className="ghost" onClick={() => setToast('Cell owners notified')}>Notify cell owners</button>
              </div>
            </div>
            <div className="card cde">
              <h3>Critical data elements · footprint</h3>
              <ul>{d.cde_footprint.map((f, i) => <li key={f.field}><span className="mono">{f.field}</span><span>{f.cells} of {f.of}{i === 0 ? ' pilot cells' : ''}</span></li>)}</ul>
            </div>
          </>
        )}
      </aside>
      {toast && <div className="toast" role="status">{toast}</div>}
    </main>
  )
}
