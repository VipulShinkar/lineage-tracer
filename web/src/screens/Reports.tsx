import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { api, useApi, type SearchResults } from '../api'
import { cellPath } from '../nav'
import { useApp } from '../Layout'
import { dates } from '../format'
import './reports.css'

export default function Reports() {
  const nav = useNavigate()
  const { contexts: c, sub, setSub } = useApp()
  const tpl = useApi(api.templates, [sub])
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<SearchResults['results'] | null>(null)

  const search = async (e: React.FormEvent) => {
    e.preventDefault()
    if (q.trim()) setHits((await api.search(q.trim())).results)
  }
  const subs = c?.submissions ?? []
  const cur = subs.find(x => x.id === sub) ?? subs[0]
  const opts = (label: string, items: string[]) => (
    <label className="field"><span>{label}</span>
      <select>{items.map(i => <option key={i}>{i}</option>)}</select></label>
  )
  return (
    <main className="main reports">
      <div className="rtop">
        <div>
          <h1>Choose a report and a number to trace</h1>
          <p className="sub">Step 1 of the journey · set the reporting context, then open a template.</p>
        </div>
        <form className="search" role="search" onSubmit={search}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-4-4" /></svg>
          <input aria-label="Search" value={q} onChange={e => { setQ(e.target.value); setHits(null) }} placeholder="Search template-row-column, DPM datapoint ID, business term or value" />
          {hits && (
            <ul className="hits">
              {hits.length === 0 && <li className="none">No matches</li>}
              {hits.map(h => <li key={h.uid}><b>{h.name}</b> <span>{h.subtitle} · {h.verb} {h.feeds_cells} cells</span></li>)}
            </ul>
          )}
        </form>
      </div>

      <div className="card filters">
        {opts('Report family', c?.report_families ?? ['COREP (EBA DPM)'])}
        {opts('Reporting entity', c?.entities ?? ['[LEGAL ENTITY]'])}
        {opts('Consolidation basis', c?.bases ?? ['Solo'])}
        <label className="field"><span>Reference date</span>
          <select value={cur?.ref_date ?? ''} onChange={e => setSub(subs.find(x => x.ref_date === e.target.value)!.id)}>
            {[...new Set(subs.map(x => x.ref_date))].map(d => <option key={d} value={d}>{dates(d)}</option>)}</select></label>
        <label className="field"><span>Submission version</span>
          <select value={cur?.id ?? ''} onChange={e => setSub(e.target.value)}>
            {subs.filter(x => x.ref_date === cur?.ref_date).map(x => <option key={x.id} value={x.id}>{dates(x.label)}</option>)}</select></label>
      </div>

      {tpl.error && <div className="state err">{tpl.error}</div>}
      <div className="rbody">
        <div className="card tablecard">
          <table className="ttable">
            <thead><tr><th>Template</th><th>Name</th><th>Pilot cells</th><th colSpan={2}>Lineage coverage</th></tr></thead>
            <tbody>
              {tpl.data?.templates.map(t => {
                const fill = t.pilot_cells ? (t.coverage.complete / t.pilot_cells) * 100 : 0
                return (
                  <tr key={t.id} className={t.in_scope ? '' : 'off'}>
                    <td className="mono code">{t.code}</td>
                    <td>{t.name}</td>
                    <td className="muted">{t.in_scope ? `${t.pilot_cells} of ${t.cells_total_in_scope}` : '0'}</td>
                    <td className="cov">
                      <span className={`bar ${t.in_scope ? '' : 'empty'}`}><i style={{ width: `${fill}%` }} /></span>
                      <span className="covlabel">{t.coverage.label}</span>
                    </td>
                    <td className="act">
                      {t.in_scope ? <Link className="btn" to={`/explorer/templates/${t.id}`}>Open</Link> : <span className="scopenote">{t.scope_note}</span>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {tpl.loading && <div className="state">Loading…</div>}
        </div>

        <div className="side">
          {tpl.data && (
            <div className="card">
              <h3>Pilot scope · {tpl.data.pilot_scope.total} cells</h3>
              <p className="desc">{tpl.data.pilot_scope.description}</p>
              <div className="chips">
                <span className="pill complete">{tpl.data.pilot_scope.complete} complete</span>
                <span className="pill partial">{tpl.data.pilot_scope.partial} partial</span>
                <span className="pill gap">{tpl.data.pilot_scope.gap} gap</span>
              </div>
            </div>
          )}
          {tpl.data && (
            <div className="card">
              <h3>Recent lineage queries</h3>
              <ul className="recent">
                {tpl.data.recent_queries.map(r => (
                  <li key={r.cell_id}><a href={cellPath(r.cell_id)} onClick={e => { e.preventDefault(); nav(cellPath(r.cell_id)) }}>{r.label}</a></li>
                ))}
              </ul>
            </div>
          )}
          <div className="note-card">Each cell carries a coverage badge: complete, partial, gap or not yet in scope. Status is shown with text as well as colour.</div>
        </div>
      </div>
    </main>
  )
}
