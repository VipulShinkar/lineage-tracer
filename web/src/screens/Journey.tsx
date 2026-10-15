import { Link } from 'react-router-dom'
import { SCREEN_ROUTES } from '../nav'
import './journey.css'

type Step = { n: number; title: string; body: string; tags: string[] }
const stage1: Step[] = [
  { n: 1, title: 'Set reporting context', body: 'Pick entity, consolidation basis, reference date and submission version.', tags: ['S01'] },
  { n: 2, title: 'Open template C 07.00', body: 'Click a template row (or search by DPM ID / row-column); choose sheet “Corporates”.', tags: ['S02'] },
  { n: 3, title: 'Select the cell', body: 'Click the 1,240.5 cell → side panel shows coverage, hops, sources → “Trace this number”.', tags: ['S02', 'S03'] },
  { n: 4, title: 'See where it came from', body: 'Hop graph back to first-hop systems; toggle System / Dataset / Attribute; gaps shown dashed.', tags: ['S03'] },
  { n: 5, title: 'See how it was sourced', body: 'Click any hop → mechanism, cut-off, actual run, record counts, field mapping, controls.', tags: ['S04'] },
  { n: 6, title: 'See what happened to it', body: 'Transformations tab → plain-English rules, version for the date, CRR reference, mapping viewer.', tags: ['S05'] },
  { n: 7, title: 'Prove it reconciles', body: 'Waterfall tab → click a step → adjustment with maker-checker; control results per hop.', tags: ['S06'] },
  { n: 8, title: 'Drill to records', body: 'Records tab → group, top-N, trace one exposure to its source key; compare to prior quarter.', tags: ['S07'] },
  { n: 9, title: 'Give the regulator evidence', body: 'Regulator view → narrative + simplified journey → Generate evidence pack.', tags: ['S08'] },
  { n: 10, title: 'Govern coverage', body: 'Coverage dashboard → gaps, certification by owner, audit log of who viewed and exported.', tags: ['S09'] },
]
const stage2: Step[] = [
  { n: 11, title: 'Pick a source element', body: 'Search a field, rule, mapping, control or record; choose date and entities.', tags: ['S10'] },
  { n: 12, title: 'See what it feeds', body: 'Fan-out impact graph + impacted-cell list; open any cell’s reverse lineage.', tags: ['S11'] },
  { n: 13, title: 'Size it and decide', body: 'Contribution per cell, what-if on ratios, resubmission flag → export impact report.', tags: ['S12'] },
]

function Card({ s, stage }: { s: Step; stage: 1 | 2 }) {
  return (
    <div className="jcard">
      <h3><span className={`jnum s${stage}`}>{s.n}</span>{s.title}</h3>
      <p>{s.body}</p>
      <div className="tags">
        {s.tags.map((t, i) => (
          <span key={t} style={{ display: 'contents' }}>
            {i > 0 && <span className="arrow" aria-hidden="true">→</span>}
            <Link className="tag" to={SCREEN_ROUTES[t]}>{t}</Link>
          </span>
        ))}
      </div>
    </div>
  )
}

export default function Journey() {
  return (
    <main className="main journey">
      <div className="jtop">
        <div>
          <div className="eyebrow jeyebrow">End-to-end user journey · click path</div>
          <h1>From a question on one COREP number to an evidence pack — and back again</h1>
          <p className="lede">Worked example throughout: C 07.00 · Corporates · Exposure value · 1,240.5m EUR · 30-Jun-2026. Each step names the click and the screen it lands on. Click any screen tag to open it.</p>
        </div>
        <aside className="personas">
          <b>Personas on this journey</b>
          <p>Regulator / supervisor — steps 1–9 (read-only, masked)</p>
          <p>Reporting analyst — all steps</p>
          <p>Data owner / change team — steps 10–13</p>
        </aside>
      </div>

      <h2 className="stage"><span className="stagetag s1">STAGE 1</span>Reverse lineage — report cell → first source</h2>
      <div className="jgrid">{stage1.map(s => <Card key={s.n} s={s} stage={1} />)}</div>

      <h2 className="stage"><span className="stagetag s2">STAGE 2</span>Forward lineage — source element → impacted cells
        <small>Step 12 can jump back into Stage 1 (screen S03) for any impacted cell.</small></h2>
      <div className="jgrid">
        {stage2.map(s => <Card key={s.n} s={s} stage={2} />)}
        <div className="jcount">
          <h3>Click count to answer the regulator</h3>
          <p>Where did it come from: <b>4 clicks</b> (context → template → cell → hop graph)</p>
          <p>How was it sourced: <b>+1 click</b> (any hop)</p>
          <p>What transformations happened: <b>+1 click</b> (Transformations tab) · proof it reconciles: <b>+1</b> (Waterfall)</p>
          <p>Evidence pack in hand: <b>+2 clicks</b> (Regulator view → Generate)</p>
        </div>
      </div>
      <p className="jfoot">All values on these screens are illustrative pilot data. Entity and people names are placeholders.</p>
    </main>
  )
}
