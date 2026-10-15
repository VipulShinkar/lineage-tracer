import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api, saveBlob, useApi, type EvidencePack } from '../api'
import { dates, int, n1 } from '../format'
import './regulator.css'

const TILES = (s: { hops: number; transformations: number; manual_adjustments: number; controls_passed: string; unexplained: number; records: number }) => [
  [String(s.hops), 'hops from source to report'], [String(s.transformations), 'transformations, all described'],
  [String(s.manual_adjustments), 'manual adjustment, approved'], [s.controls_passed, 'controls passed · 1 waived'],
  [n1(s.unexplained), 'unexplained difference'], [int(s.records), 'records behind the value'],
]

export default function Regulator() {
  const { cellId = '' } = useParams()
  const { data: d, error, loading } = useApi(() => api.regulator(cellId), [cellId])
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [format, setFormat] = useState('pdf')
  const [busy, setBusy] = useState(false)
  const [pack, setPack] = useState<EvidencePack>()
  const [err, setErr] = useState<string>()
  useEffect(() => { if (d) setPicked(new Set(d.evidence.sections.filter(s => s.default).map(s => s.key))) }, [d])

  if (error) return <div className="state err">{error}</div>
  if (!d) return <div className="state">{loading ? 'Loading…' : ''}</div>
  const ev = d.evidence
  const toggle = (k: string) => setPicked(p => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n })
  const generate = async () => {
    setBusy(true); setErr(undefined)
    try {
      const res = await api.evidencePack(cellId, ev.sections.filter(s => picked.has(s.key)).map(s => s.key), format)
      setPack(res)
      saveBlob(await api.download(res.download_url), `${res.ref}.${format}`)
    } catch (e) { setErr((e as Error).message) } finally { setBusy(false) }
  }
  return (
    <div className="cellbody reg">
      <div className="regmain">
        <section className="card narr">
          <div className="eyebrow">The journey of this number, in plain English</div>
          <p>{d.narrative}</p>
        </section>

        <ol className="stages" aria-label="Simplified journey">
          {d.stages.map((s, i) => (
            <li key={s.label} style={{ display: 'contents' }}>
              {i > 0 && <span className="sarrow" aria-hidden="true">→</span>}
              <div className={`stage ${s.manual ? 'manual' : ''} ${i === d.stages.length - 1 ? 'final' : ''}`}>
                <b>{s.label}</b><span className="v mono">{n1(s.value)}</span><small>{s.note}</small>
              </div>
            </li>
          ))}
        </ol>

        <div className="tiles">
          {TILES(d.stats).map(([v, l]) => <div className="card tile" key={l}><b>{v}</b><span>{l}</span></div>)}
        </div>

        {d.limitations.map((l, i) => (
          <div className="limit" key={i}><b>Known limitation disclosed</b><p>{dates(l.text)}</p></div>
        ))}
      </div>

      <aside className="card pack">
        <h2>Evidence pack</h2>
        <p className="ref mono">Reference {ev.next_ref} · linked to supervisory request {ev.linked_request}</p>
        <ul className="checks">
          {ev.sections.map(s => (
            <li key={s.key}><label><input type="checkbox" checked={picked.has(s.key)} onChange={() => toggle(s.key)} />{s.label}</label></li>
          ))}
        </ul>
        <div className="radios" role="radiogroup" aria-label="Format">
          {ev.formats.map(f => (
            <label key={f}><input type="radio" name="fmt" checked={format === f} onChange={() => setFormat(f)} />{f === 'docx' ? 'Word' : f.toUpperCase()}</label>
          ))}
        </div>
        <p className="fine">Watermarked with viewer, time and reference. Immutable once generated; a new version gets a new reference.</p>
        <div className="packfoot">
          {pack && <p className="made" role="status">Generated <b className="mono">{pack.ref}</b> · sha256 <span className="mono" title={pack.sha256}>{pack.sha256.slice(0, 12)}…</span> · download started</p>}
          {err && <p className="errmsg" role="alert">{err}</p>}
          <button className="btn block" onClick={generate} disabled={busy || picked.size === 0}>{busy ? 'Generating…' : 'Generate evidence pack'}</button>
          {ev.last_pack && <p className="last">Last pack for this cell: {ev.last_pack.ref} · {dates(ev.last_pack.created_on)}</p>}
        </div>
      </aside>
    </div>
  )
}
