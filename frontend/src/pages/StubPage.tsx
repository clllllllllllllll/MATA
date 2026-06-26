interface StubPageProps {
  title: string
  subtitle: string
  variant?: 'default' | 'non_nhg'
}

export const StubPage = ({ title, subtitle, variant = 'default' }: StubPageProps) => {
  const isNonNhg = variant === 'non_nhg'

  return (
    <div className={`page stub-page ${isNonNhg ? 'non-nhg-placeholder-page' : ''}`}>
      <section className={`card stub-card ${isNonNhg ? 'non-nhg-placeholder-card' : ''}`}>
        <div className="stub-card-heading">
          <span className={`status-badge ${isNonNhg ? 'status-badge-info' : 'status-badge-neutral'}`}>
            {isNonNhg ? 'Non-NHG Resident' : 'Placeholder'}
          </span>
          <h1>{title}</h1>
          <p>{subtitle}</p>
        </div>
        {isNonNhg ? (
          <>
            <p className="stub-lede">
              This entry surface is intentionally limited for this phase. The future Non-NHG Resident workflow will
              support registration, current NHG posting updates, event submission, ad-hoc submission, and past
              attendance review after the backend contract is implemented.
            </p>
            <div className="non-nhg-placeholder-grid responsive-card-grid">
              <div className="mobile-record-card">
                <span className="stub-kicker">Available now</span>
                <strong>Responsive placeholder</strong>
                <p>Readable on phone, tablet, and desktop without introducing new backend-dependent actions.</p>
              </div>
              <div className="mobile-record-card">
                <span className="stub-kicker">Deferred</span>
                <strong>Full Non-NHG workflow</strong>
                <p>Registration, login, attendance export, and current posting management remain out of scope here.</p>
              </div>
            </div>
          </>
        ) : (
          <p className="stub-lede">
            This route is a mobile-safe placeholder. The workflow remains deferred until its backend contract is ready.
          </p>
        )}
        <div className="stub-page-actions">
          <span className="mono-chip">{isNonNhg ? 'Deferred workflow' : 'Responsive stub'}</span>
          <span className="stub-action-note">
            {isNonNhg ? 'No new Non-NHG backend actions are enabled here.' : 'No backend workflow is enabled here.'}
          </span>
        </div>
      </section>
    </div>
  )
}
