import { Link, Outlet, useMatch } from 'react-router-dom'
import './tracer.css'

const STEPS = ['Initiate trace', 'Trace progress', 'Lineage and evidence']

export default function TracerLayout() {
  const m = useMatch('/trace/:id/*')
  const id = m?.params.id
  const step = !m ? 0 : m.params['*'] === 'lineage' ? 2 : 1
  const to = (i: number) => (i === 0 ? '/' : id ? (i === 1 ? `/trace/${id}` : `/trace/${id}/lineage`) : undefined)
  return (
    <div className="t-app">
      <header className="t-hdr">
        <Link to="/" className="t-logo">Lineage Tracer</Link>
        <span className="t-poc">POC</span>
        <span className="sp" />
        <nav className="t-steps" aria-label="Steps">
          {STEPS.map((s, i) => {
            const t = to(i)
            const label = `${i + 1} ${s}`
            return t && i !== step ? <Link key={s} to={t}>{label}</Link> : <span key={s} className={i === step ? 'on' : ''}>{label}</span>
          })}
        </nav>
        <Link to="/explorer" className="t-repo" title="Lineage repository (Explorer)">Repository</Link>
      </header>
      <Outlet key={m?.params.id ?? 'new'} />
    </div>
  )
}
