import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, useApi, type Reveal } from '../api'
import { useApp } from '../Layout'
import { d1, dates, int, n1, n2 } from '../format'
import './records.css'

const GROUPS = [['sector', 'Counterparty sector'], ['product', 'Product'], ['source_system', 'Source system']] as const

export default function RecordsScreen() {
  const { cellId = '' } = useParams()
  const { role, setRole, contexts, sub } = useApp()
  const subs = contexts?.submissions ?? []
  const cur = subs.find(x => x.id === sub) ?? subs[0]
  const others = subs.filter(x => x.id !== cur?.id)
  const [groupBy, setGroupBy] = useState<string>('sector')
  const [compare, setCompare] = useState('')
  const [picked, setPicked] = useState<string>()
  const [revealed, setRevealed] = useState<Record<string, Reveal>>({})
  const [asking, setAsking] = useState(false)
  const [reason, setReason] = useState('')
  const [revealErr, setRevealErr] = useState<string>()

  const cmp = compare || others[0]?.id
  const cmpSub = subs.find(x => x.id === cmp)
  const rec = useApi(() => api.records(cellId, groupBy, cmp), [cellId, groupBy, cmp])
  const d = rec.data
  const key = picked ?? d?.top[d.top.length - 1]?.record_key
  const trace = useApi(() => (key ? api.trace(key) : Promise.resolve(undefined)), [key])

  const reveal = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!key || !reason.trim()) return
    try {
      const r = await api.reveal(key, reason.trim())
      setRevealed(v => ({ ...v, [key]: r })); setAsking(false); setReason(''); setRevealErr(undefined)
    } catch (err) { setRevealErr((err as Error).message) }
  }

  if (rec.error) return <div className="state err">{rec.error}</div>
  if (!d) return <div className="state">{rec.loading ? 'Loading…' : ''}</div>
  const cmpLabel = cmpSub ? dates(cmpSub.ref_date) : 'Compare'
  const groupLabel = GROUPS.find(g => g[0] === groupBy)![1]
  const shown = key ? revealed[key] : undefined
  return (
    <div className="cellbody rec">
      <div className="main-col">
        <div className="card strip">
          <div><span>Contributing records</span><b>{int(d.contributing_records)} exposures</b></div>
          <div><span>Drill-down total</span><b>{n1(d.drilldown_total)} {d.equals_reported && <small className="ok">= reported</small>}</b></div>
          <span className="sp" />
          <label className="selbox">Group by
            <select value={groupBy} onChange={e => setGroupBy(e.target.value)}>{GROUPS.map(([v, t]) => <option key={v} value={v}>{t}</option>)}</select></label>
          <label className="selbox">Compare with
            <select value={cmp ?? ''} onChange={e => setCompare(e.target.value)}>{others.map(o => <option key={o.id} value={o.id}>{dates(o.ref_date)} · {o.version}</option>)}</select></label>
        </div>

        <div className="card flush">
          <table className="rtab">
            <thead><tr><th>{groupLabel}</th><th className="r">Records</th><th className="r">{cur ? dates(cur.ref_date) : 'Current'}</th><th className="r">{cmpLabel}</th><th className="r">Change</th></tr></thead>
            <tbody>
              {d.groups.map(g => (
                <tr key={g.key}><td>{g.key}</td><td className="r mono">{int(g.records)}</td><td className="r mono strong">{n1(g.current)}</td>
                  <td className="r mono muted">{n1(g.compare)}</td><td className={`r mono ${g.change < 0 ? 'neg' : 'pos'}`}>{d1(g.change)}</td></tr>
              ))}
            </tbody>
            <tfoot><tr><td>Total</td><td className="r mono">{int(d.total.records)}</td><td className="r mono">{n1(d.total.current)}</td>
              <td className="r mono">{n1(d.total.compare)}</td><td className="r mono pos">{d1(d.total.change)}</td></tr></tfoot>
          </table>
        </div>

        <div className="card flush">
          <h3 className="ptitle">Top contributors · click a record to trace it</h3>
          <table className="rtab top">
            <thead><tr><th>Counterparty</th><th>Sector · product</th><th>Source</th><th>Source key</th><th className="r">Exposure value</th></tr></thead>
            <tbody>
              {d.top.map(t => {
                const rv = revealed[t.record_key]
                return (
                  <tr key={t.record_key} className={t.record_key === key ? 'sel' : ''} onClick={() => setPicked(t.record_key)}>
                    <td className="mono"><button className="rowbtn" aria-pressed={t.record_key === key} onClick={() => setPicked(t.record_key)}>{rv?.counterparty ?? t.counterparty}</button></td>
                    <td>{t.sector_product}</td><td>{t.source}</td><td className="mono">{rv?.source_key ?? t.source_key}</td>
                    <td className="r mono">{n1(t.value)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="side-col">
        <div className="card trace">
          <div className="eyebrow">One record, end to end</div>
          {trace.data && key === trace.data.record_key ? (
            <>
              <h3>{trace.data.title}</h3>
              <ol>
                {trace.data.steps.map((s, i) => (
                  <li key={i}>
                    <span className="hbadge mono">{s.hop}</span>
                    <div><b>{s.label}</b><small>{s.sublabel}</small></div>
                    <span className="amt mono">{s.ccy ? `${s.ccy} ` : ''}{n2(s.amount)}</span>
                  </li>
                ))}
              </ol>
              {shown && <p className="revealed">Revealed: <span className="mono">{shown.counterparty}</span> · <span className="mono">{shown.source_key}</span> (logged)</p>}
              {d.masking.can_reveal && !shown && (asking ? (
                <form className="reveal" onSubmit={reveal}>
                  <label>Reason for reveal (audited)<input autoFocus value={reason} onChange={e => setReason(e.target.value)} placeholder="e.g. supervisor query INC-1234" /></label>
                  <div><button className="btn sm" type="submit" disabled={!reason.trim()}>Reveal</button>
                    <button type="button" className="linkbtn" onClick={() => { setAsking(false); setRevealErr(undefined) }}>Cancel</button></div>
                  {revealErr && <p className="err" role="alert">{revealErr}</p>}
                </form>
              ) : <button className="revealbtn" onClick={() => setAsking(true)}>Reveal identifiers…</button>)}
            </>
          ) : <div className="state">{trace.error ?? 'Loading…'}</div>}
        </div>

        <div className="card who">
          <h3>Who sees what</h3>
          <div className="toggle" role="group" aria-label="View as">
            <button className={role === 'analyst' ? 'on' : ''} aria-pressed={role === 'analyst'} onClick={() => setRole('analyst')}>Analyst</button>
            <button className={role === 'supervisor' ? 'on' : ''} aria-pressed={role === 'supervisor'} onClick={() => setRole('supervisor')}>Regulator</button>
          </div>
          <p>Customer identifiers are masked for every role by default. Analysts may reveal one with a reason; each reveal is logged. The regulator role cannot reveal.</p>
        </div>
      </div>
    </div>
  )
}
