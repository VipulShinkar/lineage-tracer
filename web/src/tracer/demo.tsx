// Read-only demo snapshot mode (VITE_DEMO_SNAPSHOT=true): GETs are served from /snapshot/*.json, mutations are refused.
import { useEffect, useState } from 'react'

export const DEMO = import.meta.env.VITE_DEMO_SNAPSHOT === 'true'
export type SnapItem = {
  trace_id: string; title: string; label: string; kind: string; report: string; captured: string
  pipeline_types: string[]; hops: number; proven: number; code_derived: number
}

export const snapshotGet = async <T,>(file: string): Promise<T> => {
  const res = await fetch(`/snapshot/${file}`)
  if (!res.ok) throw new Error('Not part of the demo snapshot')
  return res.json()
}

export function useSnapshotIndex() {
  const [items, set] = useState<SnapItem[]>()
  useEffect(() => { snapshotGet<SnapItem[]>('index.json').then(set, () => set([])) }, [])
  return items
}

export const capturedOn = (items?: SnapItem[]) => {
  const d = items?.map(i => i.captured).sort().pop()
  return d ? new Date(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' }) : '…'
}

export function DemoBanner() {
  const items = useSnapshotIndex()
  return <div className="t-demo" role="status">Read-only demo snapshot — traces captured from the live system on {capturedOn(items)}</div>
}
