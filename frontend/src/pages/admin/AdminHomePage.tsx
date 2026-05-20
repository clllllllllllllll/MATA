import { useNavigate } from 'react-router-dom'
import {
  IconCalendar,
  IconDatabase,
  IconFile,
  IconGrid,
  IconRefresh,
  IconSettings,
  IconUpload,
} from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { useAppState } from '../../context/useAppState'

const workspaceTiles = [
  {
    title: 'Upload Files',
    path: '/admin/upload',
    description: 'Bring in RDB, TTF, FormF1, PH and AY workbooks.',
    stat: '4 sources',
    icon: <IconUpload size={18} />,
  },
  {
    title: 'Configuration',
    path: '/admin/config/multi',
    description: 'Manage reporting periods, posting rules, and mappings.',
    stat: '8 sections',
    icon: <IconSettings size={18} />,
  },
  {
    title: 'Upload Logs',
    path: '#',
    description: 'Audit every parser run with status and timestamps.',
    stat: '47 runs',
    icon: <IconFile size={18} />,
  },
  {
    title: 'Parsed Data',
    path: '#',
    description: 'Review parser outputs and source-level entities.',
    stat: '8 tables',
    icon: <IconDatabase size={18} />,
  },
  {
    title: 'Secretary Events',
    path: '#',
    description: 'View teaching events created across postings.',
    stat: '127 events',
    icon: <IconCalendar size={18} />,
  },
  {
    title: 'Resident Submissions',
    path: '#',
    description: 'Submitted attendance records across programmes.',
    stat: '243 submitted',
    icon: <IconGrid size={18} />,
  },
]

const formatDateTime = (iso?: string) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : 'Not uploaded'

export const AdminHomePage = () => {
  const navigate = useNavigate()
  const { uploadHistory, warnings } = useAppState()

  const unresolvedWarnings = warnings.filter((item) => item.status === 'unresolved')
  const lastSyncText = uploadHistory[0]
    ? formatDateTime(uploadHistory[0].uploadedAtIso)
    : 'No uploads yet'
  const unresolvedWarningsText = `${unresolvedWarnings.length} unresolved warnings`

  return (
    <div className="page">
      <PageHero
        title="Welcome back, Demo Admin"
        subtitle="Master Admin - All programmes - System overview"
        metaInline={[`Last full sync · ${lastSyncText}`, unresolvedWarningsText]}
        actions={
          <div className="hero-action-row">
            <button type="button" className="button button-secondary" onClick={() => window.location.reload()}>
              <IconRefresh size={14} />
              Refresh
            </button>
            <button type="button" className="button button-primary" onClick={() => navigate('/admin/upload')}>
              <IconUpload size={14} />
              Upload files
            </button>
          </div>
        }
      />

      <section className="grid grid-3">
        {workspaceTiles.map((tile) =>
          tile.path === '#' ? (
            <article key={tile.title} className="tile">
              <div className="icon-wrap">{tile.icon}</div>
              <div className="t-title">{tile.title}</div>
              <div className="t-desc">{tile.description}</div>
              <div className="t-foot">
                <strong>{tile.stat}</strong>
              </div>
            </article>
          ) : (
            <button
              key={tile.title}
              type="button"
              className="tile tile-button"
              onClick={() => navigate(tile.path)}
              aria-label={`${tile.title}. ${tile.description}`}
            >
              <div className="icon-wrap">{tile.icon}</div>
              <div className="t-title">{tile.title}</div>
              <div className="t-desc">{tile.description}</div>
              <div className="t-foot">
                <strong>{tile.stat}</strong>
              </div>
            </button>
          ),
        )}
      </section>

      <section className="bottom-split">
        <article className="card">
          <div className="section-header">
            <h2>Recent uploads</h2>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>When</th>
                  <th>Programme</th>
                  <th>Warnings</th>
                </tr>
              </thead>
              <tbody>
                {uploadHistory.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No uploads yet. Start with Academic Calendar / Public Holidays.</td>
                  </tr>
                ) : (
                  uploadHistory.slice(0, 6).map((entry) => (
                    <tr key={entry.id}>
                      <td>{entry.uploadLabel}</td>
                      <td>{formatDateTime(entry.uploadedAtIso)}</td>
                      <td>{entry.programmeCode ?? 'All'}</td>
                      <td>{entry.warningsCount}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="card">
          <div className="section-header">
            <h2>Unresolved warnings</h2>
            <button type="button" className="button button-ghost" onClick={() => navigate('/admin/upload/warnings')}>
              All warnings {'->'}
            </button>
          </div>
          <ul className="warning-list">
            {unresolvedWarnings.slice(0, 5).map((warning) => (
              <li key={warning.id}>
                  <span className={`dot dot-${warning.severity}`} />
                  <div>
                    <strong>{warning.type}</strong>
                    <p>{warning.message}</p>
                  </div>
                </li>
            ))}
            {unresolvedWarnings.length === 0 ? <li>No unresolved warnings.</li> : null}
          </ul>
        </article>
      </section>
    </div>
  )
}
