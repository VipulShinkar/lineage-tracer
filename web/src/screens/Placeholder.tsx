export default function Placeholder({ title }: { title: string }) {
  return (
    <main className="main">
      <h1 className="serif" style={{ fontSize: 28, fontWeight: 500 }}>{title}</h1>
      <p style={{ color: 'var(--muted)', marginTop: 8 }}>Planned for Phase 2.</p>
    </main>
  )
}
