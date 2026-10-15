import { useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Bar, BarChart, Cell, CartesianGrid, ResponsiveContainer, XAxis, YAxis } from 'recharts'
import { api, useApi, type Waterfall } from '../api'
import { dates, n1, stamp } from '../format'
import { cellPath } from '../nav'
import './waterfall.css'

const COLORS = { total: '#1f4e78', delta: '#6d8fb4', manual: '#b4501c', reported: '#17202f' }
const AXIS_MIN = 1200

type Step = Waterfall['steps'][number]

function toBars(steps: Step[]) {
  let run = 0
  return steps.map((s, i) => {
    const last = i === steps.length - 1
    if (s.kind === 'total') {
      run = s.amount
      return { ...s, range: [AXIS_MIN, s.amount] as [number, number], color: last ? COLORS.reported : COLORS.total }
    }
    const before = run
    run = Math.round((run + s.amount) * 10) / 10
    return { ...s, range: [run, before] as [number, number], color: s.kind === 'manual' ? COLORS.manual : COLORS.delta }
  })
}
type Bar = ReturnType<typeof toBars>[number]

export default function WaterfallScreen() {
  const { cellId = '' } = useParams()
  const nav = useNavigate()
  const adjRef = useRef<HTMLDivElement>(null)
  const { data: d, error, loading } = useApi(() => api.waterfall(cellId), [cellId])
  if (error) return <div className="state err">{error}</div>
  if (!d) return <div className="state">{loading ? 'Loading…' : ''}</div>
  const bars = toBars(d.steps)
  const open = (s: Step) => {
    if (s.link.type === 'hop') nav(cellPath(cellId, `hop/${s.link.id}`))
    else if (s.link.type === 'rule') nav(cellPath(cellId, `transformations`))
    else adjRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }
  const tick = (p: { x?: number | string; y?: number | string; index?: number }) => {
    const b = bars[p.index ?? 0]
    return b ? (
      <g transform={`translate(${p.x},${p.y})`} style={{ cursor: 'pointer' }} onClick={() => open(b)}>
        <text y={20} textAnchor="middle" fontWeight={600} fontSize={14} fill="#1d2531">{b.label}</text>
        <text y={38} textAnchor="middle" fontSize={12} fill="#5d6673">{b.sublabel}</text>
      </g>
    ) : <g />
  }
  const label = (p: { x?: number | string; y?: number | string; width?: number | string; index?: number }) => {
    const b = bars[p.index ?? 0]
    if (!b) return <g />
    return <text x={Number(p.x) + Number(p.width) / 2} y={Number(p.y) - 8} textAnchor="middle" fontFamily="IBM Plex Mono" fontSize={13.5}
      fill={b.kind === 'manual' ? COLORS.manual : '#1d2531'}>{n1(b.amount)}</text>
  }
  const a = d.adjustment
  return (
    <div className="cellbody wf">
      <div className="card chartcard">
        <div className="chead">
          <h2>From source value to reported value — every movement explained</h2>
          <span className={`resid ${d.within_tolerance ? '' : 'bad'}`}>Residual {n1(d.residual)} · tolerance ±{n1(d.tolerance)} · {d.within_tolerance ? 'within tolerance' : 'outside tolerance'}</span>
        </div>
        <div className="chart">
          <ResponsiveContainer width="100%" height={360}>
            <BarChart data={bars} margin={{ top: 30, right: 20, left: 20, bottom: 40 }} barCategoryGap="22%">
              <CartesianGrid vertical={false} stroke="transparent" />
              <XAxis dataKey="key" tick={tick as never} tickLine={false} axisLine={{ stroke: '#c8c6bd' }} interval={0} />
              <YAxis hide domain={[AXIS_MIN, 1330]} />
              <Bar dataKey="range" isAnimationActive={false} label={label as never} onClick={(_, i) => open(bars[i])} cursor="pointer">
                {bars.map((b: Bar) => <Cell key={b.key} fill={b.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
        <ul className="sr-only">{d.steps.map(s => <li key={s.key}><button onClick={() => open(s)}>{s.label}: {n1(s.amount)}, open {s.link.type} {s.link.id}</button></li>)}</ul>
        <p className="axisnote">Axis starts at {n1(AXIS_MIN).replace('.0', '')} EUR m to make small steps visible · click a bar to open its rule, adjustment or hop</p>
      </div>

      <div className="bottom">
        <div className="card adj" ref={adjRef}>
          <div className="adjhead"><div><span className="eyebrow orange">Manual adjustment</span> <b className="mono">{a.id}</b></div><span className="adjamt">{n1(a.amount)}</span></div>
          <p>{dates(a.description)}</p>
          <div className="mc">
            <span><em>Maker</em> · {a.maker} · {stamp(a.maker_at)}</span>
            <span><em>Checker</em> · {a.checker} · {stamp(a.checker_at)}</span>
            <span><em>Source</em> · {a.source}</span>
            <span><em>Evidence</em> · <a href={a.evidence.url}>{a.evidence.label}</a></span>
          </div>
        </div>
        <div className="card flush">
          <div className="ctitle"><h3>Controls along the journey</h3><span>{d.controls.summary}</span></div>
          <ul className="cgrid">
            {d.controls.items.map((c, i) => (
              <li key={i}><span className={`badge ${c.status}`}>{c.status.toUpperCase()}</span><span className="hopid">{c.hop}</span>{c.name}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
