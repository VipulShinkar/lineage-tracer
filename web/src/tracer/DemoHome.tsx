import { Link } from 'react-router-dom'
import { useSnapshotIndex } from './demo'

const TYPE = (t: string) => t.replace(/_/g, ' ')

export default function DemoHome() {
  const items = useSnapshotIndex()
  return (
    <main className="t-main">
      <div className="t-titlerow">
        <div>
          <h1 className="t-h1">Reverse lineage: from a reported data point to its system of record</h1>
          <p className="t-sub">Pick a trace captured from the live system. Open the progress view or the lineage graph with its evidence.</p>
        </div>
        <Link to="/initiate" className="t-textbtn">Initiate screen (read-only)</Link>
      </div>
      {!items ? <div className="state">Loading…</div> : (
        <div className="t-cards">
          {items.map(i => (
            <article key={i.trace_id} className="t-card t-snap">
              <div className="t-eyebrow">{i.kind}</div>
              <h3>{i.title}</h3>
              <p className="t-subm mono">{i.label}</p>
              <div className="t-badges">{i.pipeline_types.map(p => <span key={p} className="t-pill">{TYPE(p)}</span>)}</div>
              <p className="t-subm">{i.hops} hops · {i.proven} proven · {i.code_derived} code-derived</p>
              <div className="t-links">
                <Link className="t-btn" to={`/trace/${i.trace_id}/lineage`}>Lineage and evidence</Link>
                <Link className="t-textbtn" to={`/trace/${i.trace_id}`}>Progress</Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </main>
  )
}
