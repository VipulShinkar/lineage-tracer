import { Link, NavLink, Outlet, Route, Routes, useLocation, useParams } from 'react-router-dom'
import { Suspense, lazy } from 'react'
import Layout, { AppProvider } from './Layout'
import { api, useApi } from './api'
import { covWord, cellVal, sheetName } from './format'
import { DEMO } from './tracer/demo'
import { cellPath } from './nav'
const TracerLayout = lazy(() => import('./tracer/TracerLayout'))
const Initiate = lazy(() => import('./tracer/Initiate'))
const Progress = lazy(() => import('./tracer/Progress'))
const TraceLineage = lazy(() => import('./tracer/Lineage'))
const DemoHome = lazy(() => import('./tracer/DemoHome'))
const Journey = lazy(() => import('./screens/Journey'))
const Reports = lazy(() => import('./screens/Reports'))
const TemplateGrid = lazy(() => import('./screens/TemplateGrid'))
const HopGraph = lazy(() => import('./screens/HopGraph'))
const HopDetail = lazy(() => import('./screens/HopDetail'))
const Transformations = lazy(() => import('./screens/Transformations'))
const WaterfallScreen = lazy(() => import('./screens/Waterfall'))
const RecordsScreen = lazy(() => import('./screens/Records'))
const Placeholder = lazy(() => import('./screens/Placeholder'))
const Regulator = lazy(() => import('./screens/Regulator'))
const CoverageScreen = lazy(() => import('./screens/CoverageScreen'))
const ImpactSearch = lazy(() => import('./screens/ImpactSearch'))
const ImpactGraph = lazy(() => import('./screens/ImpactGraph'))
const Sizing = lazy(() => import('./screens/Sizing'))

const label = (c: string) => c.replace(/^C(\d)/, 'C $1')
const tabs: [string, string, string?][] = [
  ['Hop graph', 'graph'], ['Hop detail', 'hop/3', 'hop'], ['Transformations', 'transformations'],
  ['Value waterfall', 'waterfall'], ['Records', 'records'], ['Regulator view', 'regulator'],
]

/** Cell header strip (breadcrumb, big value, coverage badge) + 6 tabs; shared by S03–S08. */
function CellLayout() {
  const { cellId = '' } = useParams()
  const { pathname } = useLocation()
  const { data } = useApi(() => api.cell(cellId), [cellId])
  const h = data?.cell_header
  return (
    <>
      <div className="cellhead">
        <div className="top">
          <div className="crumb">
            {h ? <><Link to={`/explorer/templates/${h.cell_id.split(':')[0]}?sheet=${encodeURIComponent(h.sheet)}&cell=${encodeURIComponent(h.cell_id)}`}>{label(h.template)} {h.template_name}</Link>
              {' › '}{sheetName(h.sheet)} › {h.row} {h.row_label} · {h.col} {h.col_label}</> : ' '}
          </div>
          {h && <div className="bigval"><b>{cellVal(h.value, h.unit)}</b><span>{h.unit}</span><span className={`pill ${h.coverage}`}>{covWord(h.coverage)} · {h.coverage_note}</span></div>}
        </div>
        <nav className="tabs" aria-label="Cell views">
          {tabs.map(([t, to, key]) => (
            <NavLink key={t} to={cellPath(cellId, to)} className={({ isActive }) => (isActive || (key && pathname.includes(`/${key}/`)) ? 'active' : '')}>{t}</NavLink>
          ))}
        </nav>
      </div>
      <Outlet />
    </>
  )
}

export default function App() {
  return (
    <AppProvider>
      <Suspense fallback={<div className="state">Loading…</div>}>
      <Routes>
        <Route element={<TracerLayout />}>
          <Route index element={DEMO ? <DemoHome /> : <Initiate />} />
          {DEMO && <Route path="initiate" element={<fieldset disabled className="t-ro"><Initiate /></fieldset>} />}
          <Route path="trace/:id" element={<Progress />} />
          <Route path="trace/:id/lineage" element={<TraceLineage />} />
        </Route>
        <Route path="explorer" element={<Layout />}>
          <Route index element={<Journey />} />
          <Route path="reports" element={<Reports />} />
          <Route path="templates/:template" element={<TemplateGrid />} />
          <Route path="cells/:cellId" element={<CellLayout />}>
            <Route path="graph" element={<HopGraph />} />
            <Route path="hop/:n" element={<HopDetail />} />
            <Route path="transformations" element={<Transformations />} />
            <Route path="waterfall" element={<WaterfallScreen />} />
            <Route path="records" element={<RecordsScreen />} />
            <Route path="regulator" element={<Regulator />} />
          </Route>
          <Route path="coverage" element={<CoverageScreen />} />
          <Route path="impact" element={<ImpactSearch />} />
          <Route path="impact/:uid" element={<ImpactGraph />} />
          <Route path="impact/:uid/sizing" element={<Sizing />} />
          <Route path="*" element={<Placeholder title="Not found" />} />
        </Route>
      </Routes>
      </Suspense>
    </AppProvider>
  )
}
