// Route helpers + per-screen footer/pill config (prev / requirement IDs / next), copied from the PDF.
export const DEFAULT_CELL = 'C07.00:Corporates:r0010:c0200'
export const DEFAULT_ELEMENT = 'field:collateral_master.collateral_value'
export const impactPath = (uid: string, sizing = false, search = '') => `/explorer/impact/${encodeURIComponent(uid)}${sizing ? '/sizing' : ''}${search}`
export const cellPath = (id: string, tab = 'graph') => `/explorer/cells/${encodeURIComponent(id)}/${tab}`
export const SCREEN_ROUTES: Record<string, string> = {
  S01: '/explorer/reports', S02: '/explorer/templates/C07.00', S03: cellPath(DEFAULT_CELL), S04: cellPath(DEFAULT_CELL, 'hop/3'),
  S05: cellPath(DEFAULT_CELL, 'transformations'), S06: cellPath(DEFAULT_CELL, 'waterfall'), S07: cellPath(DEFAULT_CELL, 'records'),
  S08: cellPath(DEFAULT_CELL, 'regulator'), S09: '/explorer/coverage', S10: '/explorer/impact', S11: impactPath(DEFAULT_ELEMENT), S12: impactPath(DEFAULT_ELEMENT, true),
}
type Link = { label: string; to: string; noArrow?: boolean }
export type Screen = { code: string; prev?: Link; next?: Link; text?: string }

export function resolveScreen(pathname: string, search: string): Screen {
  const p = pathname.split('/').filter(Boolean).map(decodeURIComponent).slice(1) // drop the 'explorer' prefix
  const cell = new URLSearchParams(search).get('cell') ?? DEFAULT_CELL
  if (p.length === 0) return { code: 'Journey' }
  if (p[0] === 'reports') return { code: 'S01', prev: { label: 'Journey map', to: '/explorer' }, text: 'FR-R-01, FR-R-02, FR-R-03', next: { label: 'Next: open C 07.00', to: '/explorer/templates/C07.00' } }
  if (p[0] === 'templates') return { code: 'S02', prev: { label: 'Report browser', to: '/explorer/reports' }, text: 'FR-R-02, FR-R-03, FR-R-05', next: { label: 'Next: trace the number', to: cellPath(cell) } }
  if (p[0] === 'cells') {
    const id = p[1], tab = p[2]
    if (tab === 'graph') return { code: 'S03', prev: { label: 'Template grid', to: '/explorer/templates/C07.00' }, text: 'FR-R-05, FR-R-06, FR-R-08, FR-R-10 · BR-R-09 gaps shown', next: { label: 'Next: open hop 3', to: cellPath(id, 'hop/3') } }
    if (tab === 'hop') return { code: 'S04', prev: { label: 'Hop graph', to: cellPath(id) }, text: 'FR-R-07, FR-R-09, FR-R-11, FR-R-13 · BR-R-11 to BR-R-14', next: { label: 'Next: transformations', to: cellPath(id, 'transformations') } }
    if (tab === 'transformations') return { code: 'S05', prev: { label: 'Hop detail', to: cellPath(id, 'hop/3') }, text: 'FR-R-12, FR-R-14 · BR-R-07, BR-R-16 to BR-R-21', next: { label: 'Next: prove it reconciles', to: cellPath(id, 'waterfall') } }
    if (tab === 'waterfall') return { code: 'S06', prev: { label: 'Transformations', to: cellPath(id, 'transformations') }, text: 'FR-R-13, FR-R-15, FR-R-16, FR-R-20 · BR-R-22 to BR-R-24, BR-R-29 to BR-R-31', next: { label: 'Next: drill to records', to: cellPath(id, 'records') } }
    if (tab === 'records') return { code: 'S07', prev: { label: 'Value waterfall', to: cellPath(id, 'waterfall') }, text: 'FR-R-17 to FR-R-19, FR-R-21 · BR-R-25 to BR-R-28, BR-R-34 · SEC-03, SEC-06', next: { label: 'Next: regulator view', to: cellPath(id, 'regulator') } }
    return { code: 'S08', prev: { label: 'Records', to: cellPath(id, 'records') }, text: 'FR-R-22, FR-R-23 · BR-R-32, BR-R-33 · SEC-08, SEC-12', next: { label: 'Next: coverage dashboard', to: '/explorer/coverage' } }
  }
  if (p[0] === 'coverage') return { code: 'S09', prev: { label: 'Regulator view', to: SCREEN_ROUTES.S08 }, text: 'FR-R-24, FR-R-25 · BR-R-36, BR-R-37 · SEC-11, SEC-14', next: { label: 'Next: Stage 2 forward impact', to: '/explorer/impact' } }
  if (p[0] === 'impact') {
    const uid = p[1] ?? DEFAULT_ELEMENT
    if (p.length === 1) return { code: 'S10', prev: { label: 'Coverage', to: '/explorer/coverage' }, text: 'FR-F-01 · BR-F-01, BR-F-08', next: { label: 'Next: see what it feeds', to: impactPath(uid, false, search) } }
    if (p.length === 2) return { code: 'S11', prev: { label: 'Impact search', to: '/explorer/impact' + search }, text: 'FR-F-02 to FR-F-05 · BR-F-02, BR-F-03, BR-F-06', next: { label: 'Next: size the impact', to: impactPath(uid, true, search) } }
    return { code: 'S12', prev: { label: 'Impact graph', to: impactPath(uid, false, search) }, text: 'FR-F-06, FR-F-08, FR-F-10 · BR-F-04, BR-F-05, BR-F-07, BR-F-10', next: { label: 'Back to journey map', to: '/explorer' } }
  }
  return { code: '—' }
}
