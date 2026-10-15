import { api, useApi } from '../api'
import { dateTime, dates } from '../format'
import './coverage.css'

const tone = (s: string) => (/^complete|^certified/i.test(s) ? 'ok' : /^partial|^due/i.test(s) ? 'warn' : 'bad')
const dm = (ts: string) => { const m = /^\d{4}-(\d{2})-(\d{2})[T ](\d{2}:\d{2})/.exec(ts); return m ? [`${m[2]}-${MON[+m[1] - 1]}`, m[3]] : [ts, ''] }
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

export default function CoverageScreen() {
  const cov = useApi(api.coverage, [])
  const aud = useApi(() => api.audit(8), [])
  const c = cov.data, k = c?.kpis
  return (
    <main className="main covpage">
      <div className="ctop">
        <div>
          <h1>Lineage coverage, certification and audit</h1>
          <p className="sub">Pilot scope · 10 cells across C 01.00, C 02.00, C 03.00 and C 07.00</p>
        </div>
        {c && <p className="sub">Refreshed after last run load · {dateTime(c.refreshed_at)}</p>}
      </div>
      {cov.error && <div className="state err">{cov.error}</div>}

      {k && (
        <div className="kpis">
          <div className="card kpi"><span>Pilot cells complete</span><b>{k.cells_complete}</b><small>{k.cells_note}</small></div>
          <div className="card kpi"><span>Hops certified</span><b>{k.hops_certified_pct}%</b><small>{k.hops_note}</small></div>
          <div className="card kpi"><span>Unexplained breaks</span><b className={k.unexplained_breaks ? 'bad' : 'ok'}>{k.unexplained_breaks}</b><small>above tolerance</small></div>
          <div className="card kpi"><span>Adjustments approved</span><b className="ok">{k.adjustments_approved}</b><small>maker ≠ checker</small></div>
          <div className="card kpi"><span>Open lineage gaps</span><b className={k.open_gaps ? 'bad' : 'ok'}>{k.open_gaps}</b><small>{dates(k.open_gaps_note)}</small></div>
          <div className="card kpi"><span>Evidence packs</span><b>{k.evidence_packs}</b><small>generated this quarter</small></div>
        </div>
      )}

      <div className="covbody">
        <div className="leftstack">
          {c && (
            <div className="card flush">
              <h3 className="ptitle">Coverage by template</h3>
              <table className="ctab">
                <thead><tr><th>Template</th><th className="r">Cells</th><th className="r">Complete</th><th className="r">Partial</th><th className="r">Gap</th><th className="r">Status</th></tr></thead>
                <tbody>
                  {c.by_template.map(t => (
                    <tr key={t.template}>
                      <td><b className="mono">{t.template}</b> · {t.name}</td>
                      <td className="r mono">{t.cells}</td><td className="r mono">{t.complete}</td><td className="r mono">{t.partial}</td><td className="r mono">{t.gap}</td>
                      <td className={`r st ${tone(t.status)}`}>{t.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {c && (
            <div className="card flush">
              <h3 className="ptitle">Certification by data owner · Q4 cycle</h3>
              <ul className="cert">
                {c.certification.map(o => (
                  <li key={o.owner}>
                    <span className="own">{o.owner}</span><span className="nodes mono">{o.nodes} nodes</span>
                    <span className="track" role="img" aria-label={`${o.pct}% certified`}><i style={{ width: `${o.pct}%` }} /></span>
                    <span className="pct">{o.pct}%</span><span className={`st ${tone(o.status)}`}>{o.status}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <div className="card flush auditcard">
          <div className="audhead"><h3>Audit log</h3>
            <span>Tamper-evident · retained {aud.data?.retention ?? '7 years'}
              {aud.data && <b className={aud.data.chain_valid ? 'chain ok' : 'chain bad'}> · {aud.data.chain_valid ? 'chain verified' : 'CHAIN BROKEN'}</b>}</span></div>
          {aud.error && <div className="state err">{aud.error}</div>}
          <ul className="audit">
            {aud.data?.entries.map(e => {
              const [d, t] = dm(e.ts)
              return (
                <li key={e.seq}>
                  <time className="mono" dateTime={e.ts}>{d}<br />{t}</time>
                  <div><span><b>{e.actor}</b> {e.action}</span><small>{dates(e.target)}{e.detail ? ` · ${dates(e.detail)}` : ''}</small></div>
                </li>
              )
            })}
          </ul>
        </div>
      </div>
    </main>
  )
}
