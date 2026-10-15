import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { Suspense, createContext, useContext, useEffect, useState } from 'react'
import { ROLES, api, getRole, getSub, setRole, setSubId, type Contexts, type Role } from './api'
import { dates } from './format'
import { resolveScreen } from './nav'

// Role and submission live in api.ts (they feed request headers/params); contexts just force a re-render + refetch.
type Ctx = { role: Role; setRole: (r: Role) => void; contexts?: Contexts; sub: string; setSub: (id: string) => void }
const AppContext = createContext<Ctx>({ role: 'analyst', setRole: () => {}, sub: '', setSub: () => {} })
export const useApp = () => useContext(AppContext)
export const useRole = () => useApp().role

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [role, setR] = useState<Role>(getRole())
  const [sub, setS] = useState(getSub())
  const [contexts, setContexts] = useState<Contexts>()
  useEffect(() => { api.contexts().then(setContexts).catch(() => {}) }, [])
  const value: Ctx = {
    role, contexts, sub,
    setRole: r => { setRole(r); setR(r) },
    setSub: id => { setSubId(id); setS(id) },
  }
  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

const Logo = () => (
  <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="1.8" aria-hidden="true">
    <circle cx="5" cy="12" r="2.6" /><circle cx="18" cy="5" r="2.6" /><circle cx="18" cy="19" r="2.6" />
    <path d="M7.4 10.8 15.6 6.2M7.4 13.2l8.2 4.6" />
  </svg>
)

const REVERSE = ['S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07', 'S08']
const FORWARD = ['S10', 'S11', 'S12']

export default function Layout() {
  const { pathname, search } = useLocation()
  const screen = resolveScreen(pathname, search)
  const { role, setRole: setR, contexts, sub } = useApp()
  const cls = (on: boolean) => (on ? 'active' : '')
  const submission = contexts?.submissions.find(s => s.id === sub) ?? contexts?.submissions[0]
  const entity = contexts?.entities[0] ?? '[LEGAL ENTITY]'
  const basis = contexts?.bases[0] ?? 'Solo'
  const date = submission ? dates(submission.ref_date) : '30-Jun-2026'
  const version = `Submission ${submission?.version ?? 'v1'}`
  const ref = new URLSearchParams(search).get('ref')
  const c = screen.code
  const chips: string[] = ['S02', 'S03', 'S04', 'S05', 'S06', 'S07'].includes(c) ? ['COREP', `${entity} · ${basis}`, date, version]
    : c === 'S08' ? ['COREP', `${entity} · ${basis}`, date, `${version} · submitted`]
    : c === 'S09' ? ['COREP', `${entity} · ${basis}`, date]
    : c === 'S10' ? ['COREP', entity]
    : c === 'S11' || c === 'S12' ? ['COREP', `${entity} · ${basis}`, date, ...(ref ? [ref] : [])] : []
  return (
    <div className={`app ${FORWARD.includes(c) ? 'fwd' : ''}`}>
      <header className="hdr">
        <Link to="/explorer" className="logo"><Logo />Lineage Explorer</Link>
        {chips.map(t => <span className="chip" key={t}>{t}</span>)}
        <span className="sp" />
        <nav className="nav" aria-label="Primary">
          <NavLink to="/" end>Lineage Tracer</NavLink>
          <NavLink to="/explorer/reports" className={cls(REVERSE.includes(c))}>Reverse lineage</NavLink>
          <NavLink to="/explorer/impact" className={cls(FORWARD.includes(c))}>Forward impact</NavLink>
          <NavLink to="/explorer/coverage" className={cls(c === 'S09')}>Coverage</NavLink>
        </nav>
        <label className={`rolepill ${role === 'supervisor' ? 'ro' : ''}`}>Role:
          <select aria-label="Role" value={role} onChange={e => setR(e.target.value as Role)}>
            {ROLES.map(r => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
          {role === 'supervisor' && <span> · read-only · masked</span>}
        </label>
        <span className="screenpill" title="Screen code">{c}</span>
      </header>
      <Suspense fallback={<div className="state">Loading…</div>}>
        <Outlet key={`${role}|${sub}`} />
      </Suspense>
      {(screen.prev || screen.next) && (
        <footer className="ftr">
          {screen.prev ? <Link to={screen.prev.to}>← {screen.prev.label}</Link> : <span />}
          <span>Illustrative pilot data{screen.text ? ` · ${screen.text}` : ''}</span>
          {screen.next ? <Link className="next" to={screen.next.to}>{screen.next.label}{screen.next.noArrow ? '' : ' →'}</Link> : <span />}
        </footer>
      )}
    </div>
  )
}
