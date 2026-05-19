interface StubPageProps {
  title: string
  subtitle: string
}

export const StubPage = ({ title, subtitle }: StubPageProps) => (
  <div className="page">
    <section className="card">
      <h1>{title}</h1>
      <p>{subtitle}</p>
      <p>This route is a visual placeholder for the Phase 0 demo scope.</p>
    </section>
  </div>
)
