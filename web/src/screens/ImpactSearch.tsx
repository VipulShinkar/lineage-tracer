import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, useApi } from '../api'
import { useApp } from '../Layout'
import { dates } from '../format'
import { impactPath } from '../nav'
import './impact.css'

const KINDS: [string, string][] = [['all', 'All'], ['system', 'Systems'], ['field', 'Fields'], ['rule', 'Rules'], ['mapping', 'Mappings'], ['control', 'Controls'], ['record', 'Records']]
const REASONS: [string, string][] = [['dq_incident', 'Data quality incident'], ['system_change', 'Planned system change'], ['rule_change', 'Rule or mapping change'], ['regulatory_change', 'Regulatory / taxonomy change']]

export default function ImpactSearch() {
  const nav = useNavigate()
  const { contexts, sub, setSub } = useApp()
  const [q, setQ] = useState('collateral_value')
  const [dq, setDq] = useState(q)
  const [kind, setKind] = useState('all')
  const [picked, setPicked] = useState<string>()
  const [reason, setReason] = useState('dq_incident')
  const [ref, setRef] = useState('INC-[NUMBER]')
  const subs = contexts?.submissions ?? []
  const [dates_, setDates] = useState<Set<string>>(new Set())
  const curId = sub || subs[0]?.id
  const checked = dates_.size ? dates_ : new Set(curId ? [curId] : [])

  useEffect(() => { const t = setTimeout(() => setDq(q), 250); return () => clearTimeout(t) }, [q])
  const res = useApi(() => api.search(dq, kind), [dq, kind])
  const hits = res.data?.results ?? []
  const selected = hits.find(h => h.uid === picked) ?? hits[0]

  const toggleDate = (id: string) => {
    const n = new Set(checked); n.has(id) ? n.delete(id) : n.add(id)
    if (n.size) setDates(n)
  }
  const analyse = () => {
    if (!selected) return
    const first = subs.find(s => checked.has(s.id))
    if (first && first.id !== curId) setSub(first.id)
    nav(impactPath(selected.uid, false, `?ref=${encodeURIComponent(ref)}&reason=${reason}`))
  }
  return (
    <main className="main impsearch">
      <section>
        <div className="eyebrow green">Stage 2 · Forward lineage</div>
        <h1>What does this source element feed?</h1>
        <p className="sub">Start from a system, field, rule, mapping, control or a single record. Scenario: collateral values loaded without haircut, 28–30 Jun.</p>

        <div className="bigsearch" role="search">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>
          <input aria-label="Search source elements" value={q} onChange={e => setQ(e.target.value)} />
          <span className="count" aria-live="polite">{res.loading ? '…' : `${hits.length} match${hits.length === 1 ? '' : 'es'}`}</span>
        </div>
        <div className="pills" role="group" aria-label="Element kind">
          {KINDS.map(([k, t]) => <button key={k} className={kind === k ? 'on' : ''} aria-pressed={kind === k} onClick={() => setKind(k)}>{t}</button>)}
        </div>

        {res.error && <div className="state err">{res.error}</div>}
        <div className="card flush results">
          {hits.length === 0 && !res.loading && <div className="state">No matches</div>}
          {hits.map(h => (
            <button key={h.uid} className={`hit ${h.uid === selected?.uid ? 'on' : ''}`} aria-pressed={h.uid === selected?.uid}
              onClick={() => setPicked(h.uid)} onDoubleClick={analyse}>
              <span className="kind">{h.kind.toUpperCase()}</span>
              <span className="nm"><b className="mono">{h.name}</b><small>{dates(h.subtitle)}</small></span>
              <span className="feeds">{h.verb} {h.feeds_cells} pilot cells</span>
              <span className="chev" aria-hidden="true">›</span>
            </button>
          ))}
        </div>
      </section>

      <aside className="card settings">
        <h2>Analysis settings</h2>
        <fieldset><legend>Reporting dates</legend>
          {subs.map(s => (
            <label key={s.id}><input type="checkbox" checked={checked.has(s.id)} onChange={() => toggleDate(s.id)} />{dates(s.ref_date)} · submitted {s.version}</label>
          ))}
        </fieldset>
        <fieldset><legend>Scope</legend>
          <label><input type="checkbox" defaultChecked />{contexts?.entities[0] ?? '[LEGAL ENTITY]'} · {contexts?.bases[0] ?? 'Solo'}</label>
          <label><input type="checkbox" defaultChecked />COREP pilot cells</label>
          <label className="off"><input type="checkbox" disabled />FINREP · after Day 60</label>
        </fieldset>
        <fieldset><legend>Why are you asking?</legend>
          {REASONS.map(([v, t]) => <label key={v}><input type="radio" name="why" checked={reason === v} onChange={() => setReason(v)} />{t}</label>)}
        </fieldset>
        <label className="reflabel">Link to reference<input className="refinput" value={ref} onChange={e => setRef(e.target.value)} /></label>
        <button className="btn block go" onClick={analyse} disabled={!selected}>Analyse impact</button>
      </aside>
    </main>
  )
}
