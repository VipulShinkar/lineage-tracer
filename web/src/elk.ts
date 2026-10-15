// Shared ELK helper: ELK runs in a web worker (keeps the 1.4 MB engine out of the JS chunks) and only decides
// vertical order inside each fixed lane; x positions are set by the caller from the lane index.
import ELK from 'elkjs/lib/elk-api'

const elk = new ELK({ workerFactory: () => new Worker(new URL('elkjs/lib/elk-worker.min.js', import.meta.url)) })

export async function laneY(
  nodes: { id: string; lane: number; width: number; height: number }[],
  edges: { src: string; dst: string }[],
  spacing = 42,
): Promise<Map<string, number>> {
  const lane = new Map(nodes.map(n => [n.id, n.lane]))
  const res = await elk.layout({
    id: 'root',
    layoutOptions: {
      'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.partitioning.activate': 'true',
      'elk.spacing.nodeNode': String(spacing), 'elk.layered.spacing.nodeNodeBetweenLayers': '40',
      'elk.layered.considerModelOrder.strategy': 'NODES_AND_EDGES', 'elk.layered.crossingMinimization.forceNodeModelOrder': 'true',
    },
    children: nodes.map(n => ({ id: n.id, width: n.width, height: n.height, layoutOptions: { 'elk.partitioning.partition': String(n.lane) } })),
    // ELK partitioning forbids edges inside one partition; same-lane edges are drawn by React Flow, order comes from node order
    edges: edges.filter(e => lane.get(e.src) !== lane.get(e.dst)).map((e, i) => ({ id: 'e' + i, sources: [e.src], targets: [e.dst] })),
  })
  const y = new Map(res.children!.map(c => [c.id, c.y ?? 0]))
  // same-lane edge = "feeds": keep the source above its target
  for (const e of edges) if (lane.get(e.src) === lane.get(e.dst) && y.get(e.src)! > y.get(e.dst)!) {
    const t = y.get(e.src)!; y.set(e.src, y.get(e.dst)!); y.set(e.dst, t)
  }
  return y
}

/** Free left-to-right layered layout (no lanes): returns top-left positions per node. */
export async function layoutFree(
  nodes: { id: string; width: number; height: number }[],
  edges: { src: string; dst: string }[],
): Promise<Map<string, { x: number; y: number }>> {
  const seen = new Set<string>()
  const es = edges.filter(e => e.src !== e.dst && !seen.has(e.src + '>' + e.dst) && seen.add(e.src + '>' + e.dst))
  const res = await elk.layout({
    id: 'root',
    layoutOptions: { 'elk.algorithm': 'layered', 'elk.direction': 'RIGHT', 'elk.spacing.nodeNode': '34', 'elk.layered.spacing.nodeNodeBetweenLayers': '70' },
    children: nodes.map(n => ({ id: n.id, width: n.width, height: n.height })),
    edges: es.map((e, i) => ({ id: 'e' + i, sources: [e.src], targets: [e.dst] })),
  })
  return new Map(res.children!.map(c => [c.id, { x: c.x ?? 0, y: c.y ?? 0 }]))
}
