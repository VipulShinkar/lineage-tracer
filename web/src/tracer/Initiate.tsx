import { useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { disp, tracer, type Report, type SystemType, type Table } from './api'
import { dates, n1, n2 } from '../format'

type F = Record<string, string>
const DEFAULTS: Record<SystemType, F> = {
  superset: { url: 'http://127.0.0.1:8088', user: 'admin', password: '', object: '' },
  postgresql: { host: '127.0.0.1:5432', database: 'reporting_db', user: 'lineage_ro', password: '', object: '' },
  sqlite: { path: '', object: '' },
}
const REQUIRED: Record<SystemType, string[]> = {
  superset: ['url', 'user', 'password'], postgresql: ['host', 'database', 'user', 'password'], sqlite: ['path'],
}
const LABEL: Record<SystemType, string> = { superset: 'Superset', postgresql: 'PostgreSQL', sqlite: 'SQLite' }
const human = (s: string) => { const t = s.replace(/_/g, ' '); return t[0].toUpperCase() + t.slice(1) }
const isCode = (s: string) => /^[a-z]?\d{2,}$/i.test(s)
const fmt = (t: Table, v: number) => (t.unit === 'USD' ? n2(v) : n1(v))

function Field({ label, k, f, set, type = 'text', ph }: { label: string; k: string; f: F; set: (k: string, v: string) => void; type?: string; ph?: string }) {
  return (
    <label className="t-field"><span>{label}</span>
      <input type={type} value={f[k] ?? ''} placeholder={ph} autoComplete="off" onChange={e => set(k, e.target.value)} />
    </label>
  )
}

export default function Initiate() {
  const nav = useNavigate()
  const fileRef = useRef<HTMLInputElement>(null)
  const [dir, setDir] = useState<'reverse' | 'forward'>('reverse')
  const [report, setReport] = useState<Report>()
  const [upErr, setUpErr] = useState<string>()
  const [busy, setBusy] = useState(false)
  const [drag, setDrag] = useState(false)
  const [tableId, setTableId] = useState('')
  const [sel, setSel] = useState<{ row: number; col: string }>()
  const [type, setType] = useState<SystemType>('postgresql')
  const [f, setF] = useState<F>(DEFAULTS.postgresql)
  const [err, setErr] = useState<string>()
  const [starting, setStarting] = useState(false)
  const [mode, setMode] = useState<'datapoint' | 'report'>('datapoint')
  const [toast, setToast] = useState<string>()
  async function clearSaved() {
    if (!confirm('Clear all saved connections? Credentials will be asked for again.')) return
    let msg = 'Saved connections cleared'
    try { await tracer.clearSystems() } catch (e) { const m = (e as Error).message; msg = /not found|not allowed|404|405/i.test(m) ? 'Clearing saved connections is not available on this server yet' : m }
    setToast(msg); setTimeout(() => setToast(undefined), 3500)
  }

  const table = report?.tables.find(t => t.id === tableId)
  const setField = (k: string, v: string) => setF(o => ({ ...o, [k]: v }))
  const pickType = (t: SystemType, title = report?.meta.title) => { setType(t); setF({ ...DEFAULTS[t], ...(t === 'superset' && title ? { object: title } : {}) }) }

  const pickTable = (t?: Table) => {
    setTableId(t?.id ?? '')
    setSel(t && t.default_row != null && t.default_column ? { row: t.default_row, col: t.default_column } : undefined)
  }

  async function upload(file?: File) {
    if (!file) return
    setBusy(true); setUpErr(undefined)
    try {
      const r = await tracer.upload(file)
      setReport(r); pickTable(r.tables[0])
      pickType(type, r.meta.title)
    } catch (e) { setUpErr((e as Error).message) } finally { setBusy(false) }
  }

  const row = table?.rows.find(r => r.index === sel?.row)
  const value = row && sel ? row.values[sel.col] : undefined
  const ready = !!report && (mode === 'report' ? !!table : !!sel && value != null) && REQUIRED[type].every(k => f[k]?.trim())

  async function start() {
    if (!report || (mode === 'datapoint' && !sel)) return
    setStarting(true); setErr(undefined)
    try {
      const source = {
        type, name: type === 'superset' ? 'superset' : type === 'postgresql' ? f.database : f.path.split(/[\\/]/).pop(),
        url: f.url, host: f.host, database: f.database, path: f.path, user: f.user, password: f.password, object: f.object || undefined,
      }
      const { trace_id } = await tracer.start({ report_id: report.report_id, mode, data_point: mode === 'report' ? { table_id: tableId } : { table_id: tableId, row: sel!.row, column: sel!.col }, direction: 'reverse', source })
      nav(`/trace/${trace_id}`)
    } catch (e) { setErr((e as Error).message); setStarting(false) }
  }

  const m = report?.meta
  const meta: [string, string | undefined][] = m ? [
    ['Regulatory return', m.return_type], ['Reporting entity', m.entity], ['Reporting reference date', m.ref_date ? dates(m.ref_date) : undefined],
    ['Submission version', m.version], ['Delivered to', m.delivered_to],
  ] : []

  const keyHead = table?.key_columns ?? []
  const caption = table && row && sel ? (() => {
    const vals = keyHead.map(k => row.key[k]).filter(Boolean)
    const names = vals.filter(v => !isCode(v))
    const codes = vals.filter(isCode).map(v => 'r' + v.replace(/^r/i, ''))
    const tparts = table.title.split(' · ')
    const col = isCode(sel.col) ? 'c' + sel.col : sel.col
    const val = value != null ? `${fmt(table, value)}${table.unit ? ' ' + table.unit : ''}` : ''
    return { a: [tparts[tparts.length - 1], ...names, table.column_labels?.[sel.col]].filter(Boolean).join(' · '), b: [tparts.length > 1 ? tparts[0] : '', ...codes, col, val].filter(Boolean).join(' · ') }
  })() : undefined

  return (
    <main className="t-main">
      <div className="t-titlerow">
        <div>
          <h1 className="t-h1">Reverse lineage: from a reported data point to its system of record</h1>
          <p className="t-sub">Upload the regulatory report, select the data point and identify the system from which the report was obtained.</p>
        </div>
        <div className="t-seg" role="group" aria-label="Direction">
          <button className={dir === 'reverse' ? 'on' : ''} onClick={() => setDir('reverse')}>Reverse lineage</button>
          <button className={dir === 'forward' ? 'on' : ''} onClick={() => setDir('forward')}>Forward lineage</button>
        </div>
      </div>

      {dir === 'forward' ? (
        <section className="t-card t-soon">
          <h3>Forward lineage is coming next</h3>
          <p>Start from a source attribute and see every report cell it feeds. Use reverse lineage for now, or open the repository to browse forward impact.</p>
        </section>
      ) : (
        <div className="t-cols">
          <section className="t-card">
            <h3>1. Regulatory report</h3>
            <div className={`t-drop ${drag ? 'over' : ''}`}
              onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
              onDrop={e => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files[0]) }}>
              <span>XBRL instance, PDF or template</span>
              <button className="t-btn-o" onClick={() => fileRef.current?.click()} disabled={busy}>{busy ? 'Reading…' : 'Choose file'}</button>
              <input ref={fileRef} type="file" hidden data-testid="file" accept=".pdf,.xbrl,.xml,.csv,.xlsx" onChange={e => { upload(e.target.files?.[0]); e.target.value = '' }} />
            </div>
            {upErr && <p className="t-err">{upErr}</p>}
            {report && (
              <>
                <div className="t-chip"><span className="mono">{report.file_name}</span><b>Loaded</b></div>
                <dl className="t-meta">
                  {meta.filter(([, v]) => v).map(([k, v]) => <div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}
                </dl>
              </>
            )}
          </section>

          <section className="t-card">
            <div className="t-c2head">
              <h3>2. Data point</h3>
              {report && (
                <label className="t-tpl">Template
                  <select value={tableId} onChange={e => pickTable(report.tables.find(t => t.id === e.target.value))}>
                    {report.tables.map(t => <option key={t.id} value={t.id}>{t.title}</option>)}
                  </select>
                </label>
              )}
            </div>
            <div className="t-seg t-mode" role="group" aria-label="Trace mode">
              <button className={mode === 'datapoint' ? 'on' : ''} onClick={() => setMode('datapoint')}>Trace a data point</button>
              <button className={mode === 'report' ? 'on' : ''} onClick={() => setMode('report')}>Trace whole report</button>
            </div>
            {!table ? <p className="t-empty">Load a report to choose a data point.</p> : (
              <>
                <div className="t-gridwrap">
                  <table className="t-grid">
                    <thead><tr>
                      {keyHead.map(k => <th key={k}>{human(k)}</th>)}
                      {table.value_columns.map(c => <th key={c} className="num mono">{c}</th>)}
                    </tr></thead>
                    <tbody>
                      {table.rows.map(r => (
                        <tr key={r.index}>
                          {keyHead.map(k => <td key={k} className={isCode(r.key[k] ?? '') ? 'mono code' : ''}>{disp(r.key[k])}</td>)}
                          {table.value_columns.map(c => {
                            const v = r.values[c], on = sel?.row === r.index && sel.col === c
                            return (
                              <td key={c} className="num">
                                {v == null ? <span className="nil">–</span> : mode === 'report' ? <span className="t-cell will mono">{fmt(table, v)}</span> :
                                  <button className={`t-cell mono ${on ? 'on' : ''}`} aria-pressed={on} onClick={() => setSel({ row: r.index, col: c })}>{fmt(table, v)}</button>}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {mode === 'report' ? <div className="t-caption"><p>Whole report: every highlighted value in {table.title} will be traced.</p></div> : caption ? <div className="t-caption"><p>{caption.a}</p><p className="mono">{caption.b}</p></div>
                  : <p className="t-empty">Click a value to select the data point to trace.</p>}
              </>
            )}
          </section>

          <section className="t-card t-src">
            <h3>3. Report source system</h3>
            <p className="t-hint">The system from which the report was generated or obtained. Access is read-only.</p>
            <label className="t-field"><span>System type</span>
              <select value={type} onChange={e => pickType(e.target.value as SystemType)}>
                {(Object.keys(LABEL) as SystemType[]).map(t => <option key={t} value={t}>{LABEL[t]}</option>)}
              </select>
            </label>
            {type === 'superset' && <>
              <Field label="URL" k="url" f={f} set={setField} />
              <div className="t-two"><Field label="User" k="user" f={f} set={setField} /><Field label="Password" k="password" f={f} set={setField} type="password" /></div>
              <Field label="Chart title" k="object" f={f} set={setField} />
            </>}
            {type === 'postgresql' && <>
              <Field label="Host" k="host" f={f} set={setField} />
              <Field label="Database" k="database" f={f} set={setField} />
              <div className="t-two"><Field label="Read-only user" k="user" f={f} set={setField} /><Field label="Password" k="password" f={f} set={setField} type="password" /></div>
              <Field label="Table or view (optional)" k="object" f={f} set={setField} ph="defaults to the report title" />
            </>}
            {type === 'sqlite' && <>
              <Field label="File path" k="path" f={f} set={setField} ph="D:\data\reporting.db" />
              <Field label="Table or view (optional)" k="object" f={f} set={setField} ph="defaults to the report title" />
            </>}
            <div className="t-push">
              {err && <p className="t-err">{err}</p>}
              <button className="t-btn" disabled={!ready || starting} onClick={start}>{starting ? 'Connecting…' : 'Connect and initiate trace'}</button>
              <button type="button" className="t-clear" onClick={clearSaved}>Clear saved connections</button>
            </div>
          </section>
        </div>
      )}
      {toast && <div className="t-toast" role="status">{toast}</div>}
    </main>
  )
}
