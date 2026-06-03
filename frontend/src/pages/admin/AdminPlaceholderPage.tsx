import { useNavigate } from 'react-router-dom'
import { PageHero } from '../../components/PageHero'

interface AdminPlaceholderPageProps {
  title: string
  subtitle: string
  note: string
  actionLabel?: string
  actionPath?: string
}

export const AdminPlaceholderPage = ({
  title,
  subtitle,
  note,
  actionLabel,
  actionPath,
}: AdminPlaceholderPageProps) => {
  const navigate = useNavigate()

  return (
    <div className="page">
      <PageHero title={title} subtitle={subtitle} />
      <section className="card control-panel">
        <h2>Pending implementation</h2>
        <p className="inline-muted">{note}</p>
        {actionLabel && actionPath ? (
          <button type="button" className="button button-primary" onClick={() => navigate(actionPath)}>
            {actionLabel}
          </button>
        ) : null}
      </section>
    </div>
  )
}
