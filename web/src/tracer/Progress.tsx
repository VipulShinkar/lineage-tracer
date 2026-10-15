import { Fragment, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { disp, tracer, type Phase, type Step, type Trace } from './api'
import { dates, n1, n2 } from '../format'

const PHASES: [Phase, string][] = [['connect', 'Connect'], ['locate_attribute', 'Locate attribute'], ['identify_source', 'Identify source'], ['identify_consumers', 'Identify consumers']]
const PILL: Record<Step['status'], string> = { identified: 'Identified', connection_required: 'Connection required', scanning: 'Scanning', unresolved: 'Unresolved', failed: 'Failed' }
const list = (a: string[]) => (a.length ? disp(a.join(', ')) : '—')

/** Pending system name in bold, dotted identifiers (table.column) in mono. */
function Msg({ text, bold }: { text: string; bold: string }) {
  const esc = bold.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const parts = text.split(new RegExp(`(\\b${esc}\\b|\\b\\w+(?:\\.\\w+)+\\b)`))
  return <>{parts.map((p, i) => (p === bold ? <b key={i}>{p}</b> : i % 2 ? <code key={i}>{p}</code> : <Fragment key={i}>{p}</Fragment>))}</>
}

function ConnectForm({ id, t, onDone }: { id: string; t: Trace; onDone: () => void }) {
  const p = t.pending!
  const [f, setF] = useState({ host: p.host_hint ?? '', database: p.database_hint ?? '', user: 'lineage_ro', password: '' })
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string>()
  const set = (k: string, v: string) => setF(o => ({ ...o, [k]: v }))
  const sqlite = p.type === 'sqlite'
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setBusy(true); setErr(undefined)
    try {
      await tracer.connect(id, { system: p.system, type: p.type, ...(sqlite ? { path: f.host } : { host: f.host, database: f.database }), user: f.user, password: f.password })
      onDone()
    } catch (x) { setErr((x as Error).message) } finally { setBusy(false) }
  }
  return (
    <form onSubmit={submit} className="t-connect">
      <label className="t-field"><span>{sqlite ? 'File path' : 'Host'}</span><input value={f.host} onChange={e => set('host', e.target.value)} /></label>
      {!sqlite && <label className="t-field"><span>Database</span><input value={f.database} onChange={e => set('database', e.target.value)} /></label>}
      <div className="t-two">
        <label className="t-field"><span>Read-only user</span><input value={f.user} onChange={e => set('user', e.target.value)} /></label>
        <label className="t-field"><span>Password</span><input type="password" autoComplete="off" value={f.password} onChange={e => set('password', e.target.value)} /></label>
      </div>
      <div className="t-push">
        {err && <p className="t-err" role="alert">{err}</p>}
        <button className="t-btn" disabled={busy || !f.user || !f.password}>{busy ? 'Connecting…' : 'Connect read-only'}</button>
      </div>
    </form>
  )
}

export default function Progress() {
  const { id = '' } = useParams()
  const nav = useNavigate()
  const [t, setT] = useState<Trace>()
  const [err, setErr] = useState<string>()
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let live = true, timer: number
    const done = () => t?.status === 'complete' || t?.status === 'failed'
    const poll = async () => {
      try { const r = await tracer.trace(id); if (!live) return; setT(r); setErr(undefined); if (r.status === 'complete' || r.status === 'failed') return }
      catch (e) { if (live) setErr((e as Error).message) }
      if (live) timer = window.setTimeout(poll, 1000)
    }
    if (!done()) poll()
    return () => { live = false; clearTimeout(timer) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, tick])

  if (!t) return <div className="state">{err ? <span className="t-err">{err}</span> : 'Loading…'}</div>
  const complete = t.status === 'complete'
  const h = t.header
  const value = h.value == null ? (/whole report/i.test(h.label) ? '' : 'whole report') : `${h.unit === 'USD' ? n2(h.value) : n1(h.value)}${h.unit ? ' ' + h.unit : ''}`
  const sub = ['Reverse', h.label, value, h.ref_date ? dates(h.ref_date) : ''].filter(Boolean).join(' · ')
  const stats: [string, string][] = [
    [String(t.stats.systems_connected), 'systems connected'],
    [`${t.stats.sor_reached} of ${t.stats.sor_known}`, 'systems of record reached'],
    [String(t.stats.branches_outstanding), t.stats.branches_outstanding === 1 ? 'branch outstanding' : 'branches outstanding'],
  ]
  const phase = t.pending?.phase

  return (
    <main className="t-main">
      <div className="t-titlerow">
        <div>
          <h1 className="t-h1">{complete ? 'Reverse lineage complete' : t.status === 'failed' ? 'Reverse lineage failed' : 'Reverse lineage in progress'}</h1>
          <p className="t-subm mono">{sub}</p>
        </div>
        <div className="t-stats">{stats.map(([v, l]) => <div key={l}><b>{v}</b><span>{l}</span></div>)}</div>
      </div>
      {t.error && <p className="t-err t-banner" role="alert">{t.error}</p>}
      <div className="t-prog">
        <section className="t-card t-steps-card">
          <table className="t-table">
            <thead><tr><th>#</th><th>System</th><th>Attribute held in</th><th>Sourced from</th><th>Consumed by</th><th>Status</th></tr></thead>
            <tbody>
              {t.steps.map(s => (
                <tr key={s.n} className={s.status === 'connection_required' ? 'warn' : ''}>
                  <td className="n">{s.n}</td>
                  <td><b>{disp(s.system)}</b></td>
                  <td className="mono">{list(s.attribute_held_in)}</td>
                  <td className={`mono ${s.sourced_from_is_sor ? 'sor' : ''}`}>{list(s.sourced_from)}</td>
                  <td className="mono grey">{list(s.consumed_by)}</td>
                  <td><span className={`t-pill ${s.status}`}>{PILL[s.status]}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="t-foot">One row per system connected, in the order traced. Row 1 is the report source system identified by the user.</p>
        </section>

        <aside className="t-card t-next">
          {t.status === 'connection_required' && t.pending ? (
            <>
              <div className="t-eyebrow">Next source identified</div>
              <div className="t-phases">{PHASES.map(([k, l]) => <span key={k} className={k === phase ? 'cur' : ''}>{l}</span>)}</div>
              <p className="t-msg"><Msg text={t.pending.message} bold={t.pending.system} /></p>
              <ConnectForm key={t.pending.system} id={id} t={t} onDone={() => setTick(x => x + 1)} />
            </>
          ) : complete ? (
            <>
              <div className="t-eyebrow">Trace complete</div>
              <p className="t-msg">{t.stats.sor_reached} of {t.stats.sor_known} systems of record reached across {t.steps.length} systems.</p>
              <div className="t-push"><Link className="t-btn" to={`/trace/${id}/lineage`}>View lineage and evidence</Link></div>
            </>
          ) : (
            <>
              <div className="t-eyebrow">{t.status === 'failed' ? 'Trace failed' : 'Scanning'}</div>
              <p className="t-msg">{t.status === 'failed' ? 'The trace stopped before reaching every system of record.' : 'Reading system catalogs read-only. The next source will appear here if connection details are needed.'}</p>
              {t.status === 'failed' && <div className="t-push"><button className="t-btn" onClick={() => nav('/')}>New trace</button></div>}
            </>
          )}
        </aside>
      </div>
    </main>
  )
}
