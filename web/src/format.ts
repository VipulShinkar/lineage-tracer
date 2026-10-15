const nf = (d: number) => new Intl.NumberFormat('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
/** 1 dp, thousands separator, true minus. */
export const n1 = (v: number) => (v < 0 ? '−' : '') + nf(1).format(Math.abs(v))
/** Signed delta: +10.7 / −2.1 */
export const d1 = (v: number) => (v > 0 ? '+' : '') + n1(v)
/** Grid style: negatives in parentheses. */
export const paren = (v: number) => (v < 0 ? `(${nf(1).format(-v)})` : nf(1).format(v))
export const int = (v: number) => nf(0).format(v)
export const n2 = (v: number) => (v < 0 ? '−' : '') + nf(2).format(Math.abs(v))
export const covWord = (c: string) => ({ complete: 'Complete', partial: 'Partial', gap: 'Gap', not_in_scope: 'Not in scope' } as Record<string, string>)[c] ?? c

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const ISO = /(\d{4})-(\d{2})-(\d{2})/g
/** Replace every ISO date (YYYY-MM-DD) in a string with dd-Mon-yyyy. Other text passes through. */
export const dates = (s?: string) => (s ?? '').replace(ISO, (_, y, m, d) => `${d}-${MON[+m - 1]}-${y}`)
/** ISO timestamp -> "07-Jul 16:12" (no tz conversion, PDF style). Non-ISO input passes through. */
export const stamp = (s?: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2})/.exec(s ?? '')
  return m ? `${m[3]}-${MON[+m[2] - 1]} ${m[4]}` : dates(s)
}
/** ISO timestamp -> "12-Nov-2026 22:10". */
export const dateTime = (s?: string) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}:\d{2})/.exec(s ?? '')
  return m ? `${m[3]}-${MON[+m[2] - 1]}-${m[1]} ${m[4]}` : dates(s)
}
/** Human sheet name from a cell-id sheet segment (Secured_by_immovable_property). */
export const sheetName = (s: string) => s.replace(/_/g, ' ')
/** Cell value with its unit: % cells use 2 dp. */
export const cellVal = (v: number, unit?: string) => (unit === '%' ? n2(v) : n1(v))
