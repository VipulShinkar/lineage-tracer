import { useEffect } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, useApi } from '../api'
import { cellVal, covWord, n1, paren, n2, sheetName } from '../format'
import { cellPath } from '../nav'
import './grid.css'

export default function TemplateGrid() {
  const { template = 'C07.00' } = useParams()
  const [sp, setSp] = useSearchParams()
  const sheetParam = sp.get('sheet') ?? undefined
  const g = useApi(() => api.grid(template, sheetParam), [template, sheetParam])
  const sheet = g.data?.sheet ?? sheetParam ?? ''
  // default selection: the first partial cell, else the first in-pilot cell
  const cells = g.data?.rows.flatMap(r => r.cells) ?? []
  const fallback = (cells.find(c => c.coverage === 'partial') ?? cells.find(c => c.coverage !== 'not_in_scope') ?? cells[0])?.cell_id
  const selected = sp.get('cell') ?? fallback
  const side = useApi(() => (selected ? api.cell(selected) : Promise.resolve(undefined)), [selected])
  const select = (cell?: string, sh = sheet) => setSp({ sheet: sh, ...(cell ? { cell } : {}) }, { replace: true })
  const two = template === 'C03.00' || g.data?.template.id === 'C03.00'
  const fmt = (v: number) => (two ? n2(v) : paren(v))
  // keep ?cell= in the URL so the footer "Next: trace the number" follows the selection
  useEffect(() => { if (g.data && !sp.get('cell') && fallback) setSp({ sheet: g.data.sheet, cell: fallback }, { replace: true }) }, [g.data, fallback]) // eslint-disable-line react-hooks/exhaustive-deps
  const t = g.data?.template
  const h = side.data?.cell_header

  return (
    <main className="main gridpage">
      <section>
        <div className="crumb"><Link to="/explorer/reports">COREP</Link> › {t?.code ?? template}</div>
        <h1>{t ? `${t.code} · ${t.name}` : ' '}</h1>
        <div className="sheets" role="tablist" aria-label="Exposure class (sheet)">
          <span className="sheetlabel">Exposure class (sheet):</span>
          {g.data?.sheets.map(s => (
            <button key={s} role="tab" aria-selected={s === sheet} className={s === sheet ? 'on' : ''} onClick={() => select(undefined, s)}>{s}</button>
          ))}
        </div>
        {g.error && <div className="state err">{g.error}</div>}
        {g.data && (
          <div className="card gridcard">
            <table className="dgrid">
              <thead>
                <tr><th className="l">Row</th><th className="l">Item</th>
                  {g.data.columns.map(c => <th key={c.code} className={`r ${'c' + c.code === h?.col ? 'selcol' : ''}`}>{c.code} · {c.label}</th>)}</tr>
              </thead>
              <tbody>
                {g.data.rows.map(r => (
                  <tr key={r.code}>
                    <td className="mono rowcode">{r.code}</td>
                    <td className={r.bold ? 'b' : ''}>{r.label}</td>
                    {r.cells.map(c => {
                      const on = c.cell_id === selected
                      return (
                        <td key={c.col} className={`r num ${'c' + c.col === h?.col ? 'selcol' : ''}`}>
                          <button className={`cellbtn ${on ? 'on' : ''}`} onClick={() => select(c.cell_id)} aria-pressed={on}
                            aria-label={`${r.label} ${c.col}: ${fmt(c.value)}, ${covWord(c.coverage)}`}>
                            <span className={`dot ${c.coverage}`} aria-hidden="true" />{fmt(c.value)}
                          </button>
                        </td>
                      )
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="legend">
          <span><i className="dot complete" />Complete lineage</span><span><i className="dot partial" />Partial</span>
          <span><i className="dot gap" />Gap</span><span><i className="dot" />Not in pilot</span>
          <span>· Amounts in EUR millions · row and column codes simplified for illustration</span>
        </div>
      </section>

      <aside className="card sidepanel" aria-label="Selected cell">
        {side.data && h && (
          <>
            <div className="eyebrow">Selected cell</div>
            <h2>{sheetName(h.sheet)} · {h.row_label} · {h.col_label}</h2>
            <div className="ids mono">{h.template} · {h.row} · {h.col} · DPM {side.data.dpm_id.replace(/^\[(DPM )?/, '[')}</div>
            <div className="val"><b>{cellVal(h.value, h.unit)}</b><span>{h.unit}</span></div>
            <div className={`covbanner ${h.coverage}`}>{covWord(h.coverage)} lineage{h.coverage_note ? ` · ${h.coverage_note}` : ''}{side.data.gap_summary ? ` (${shortGap(side.data.gap_summary)})` : ''}</div>
            <div className="stats">
              <div><span>Hops</span><b>{side.data.hops}</b></div>
              <div><span>First-hop systems</span><b>{side.data.first_hop_systems}</b></div>
              <div><span>Transformations</span><b>{side.data.transformations}</b></div>
              <div className={side.data.manual_adjustments.count ? 'manual' : ''}><span>Manual adjustments</span>
                <b>{side.data.manual_adjustments.count} · {n1(side.data.manual_adjustments.total)}</b></div>
            </div>
            <p className="def">{side.data.business_definition}</p>
            <Link className="btn block tracebtn" to={cellPath(selected!)}>Trace this number <span aria-hidden="true">→</span></Link>
          </>
        )}
        {side.loading && !side.data && <div className="state">Loading…</div>}
        {side.error && <div className="state err">{side.error}</div>}
      </aside>
    </main>
  )
}

/** "Collateral haircut table: source not yet mapped…" -> "collateral haircut table" (banner shows the gap name, not the description). */
const shortGap = (t: string) => t.split(/[:.—]/)[0].trim().toLowerCase()
