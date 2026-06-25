import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { listUploadLogs } from '../../api/uploadLogs'
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
import { uploadLabels } from '../../config/frontendConfig'
import { useAppState } from '../../context/useAppState'
import type { UploadType } from '../../types/app'
import type { UploadLogListItem } from '../../types/upload'

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
    path: '/admin/config',
    description: 'Manage reporting periods, posting rules, and mappings.',
    stat: '8 sections',
    icon: <IconSettings size={18} />,
  },
  {
    title: 'Upload Logs',
    path: '/admin/upload-logs',
    description: 'Audit every parser run with status and timestamps.',
    stat: 'Latest logs available',
    icon: <IconFile size={18} />,
  },
  {
    title: 'Live Data',
    path: '/admin/parsed-data',
    description: 'Review uploaded records, source evidence, and audited corrections.',
    stat: 'Correction workflow',
    icon: <IconDatabase size={18} />,
  },
  {
    title: 'Secretary Events',
    path: '/admin/secretary-events',
    description: 'View teaching events created across postings.',
    stat: 'Pending endpoint',
    icon: <IconCalendar size={18} />,
  },
  {
    title: 'Resident Submissions',
    path: '/admin/submissions',
    description: 'Submitted attendance records across programmes.',
    stat: 'Read-only view',
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

const getUploadLabel = (uploadType: string) => {
  if (uploadType in uploadLabels) {
    return uploadLabels[uploadType as UploadType]
  }
  return uploadType || 'Upload'
}

const formatWarningsStatus = (log: UploadLogListItem) => {
  if (log.warning_count > 0) {
    return String(log.warning_count)
  }
  return log.status ? `${log.status} / warnings 0` : '0'
}

export const AdminHomePage = () => {
  const navigate = useNavigate()
  const { demoAdminId, demoAdminProgrammes } = useAppState()
  const [uploadLogs, setUploadLogs] = useState<UploadLogListItem[]>([])
  const [uploadLogsLoading, setUploadLogsLoading] = useState(true)
  const [uploadLogsError, setUploadLogsError] = useState<string | null>(null)

  const fetchUploadLogs = useCallback(
    () =>
      listUploadLogs({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel: 'master',
        limit: 6,
      }).then((response) => response.items),
    [demoAdminId, demoAdminProgrammes],
  )

  const refreshUploadLogs = useCallback(async () => {
    setUploadLogsLoading(true)
    setUploadLogsError(null)
    try {
      const rows = await fetchUploadLogs()
      setUploadLogs(rows)
    } catch (error) {
      setUploadLogs([])
      setUploadLogsError(error instanceof Error ? error.message : 'Unable to load upload logs.')
    } finally {
      setUploadLogsLoading(false)
    }
  }, [fetchUploadLogs])

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const rows = await fetchUploadLogs()
        if (!active) {
          return
        }
        setUploadLogs(rows)
        setUploadLogsError(null)
      } catch (error) {
        if (!active) {
          return
        }
        setUploadLogs([])
        setUploadLogsError(error instanceof Error ? error.message : 'Unable to load upload logs.')
      } finally {
        if (active) {
          setUploadLogsLoading(false)
        }
      }
    })()
    return () => {
      active = false
    }
  }, [fetchUploadLogs])

  const lastSyncText = uploadLogs[0]
    ? formatDateTime(uploadLogs[0].uploaded_at)
    : 'No uploads yet'

  return (
    <div className="page">
      <PageHero
        title="Welcome back, Demo Admin"
        subtitle="Master Admin - All programmes - System overview"
        metaInline={[`Last full sync - ${lastSyncText}`, 'Persisted warning review']}
        actions={
          <div className="hero-action-row">
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void refreshUploadLogs()}
              disabled={uploadLogsLoading}
            >
              <IconRefresh size={14} />
              {uploadLogsLoading ? 'Refreshing' : 'Refresh'}
            </button>
          </div>
        }
      />

      <section className="grid grid-3">
        {workspaceTiles.map((tile) => (
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
        ))}
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
                  <th>Warnings / status</th>
                </tr>
              </thead>
              <tbody>
                {uploadLogsLoading ? (
                  <tr>
                    <td colSpan={4}>Loading upload logs...</td>
                  </tr>
                ) : uploadLogsError ? (
                  <tr>
                    <td colSpan={4}>Upload logs could not be loaded: {uploadLogsError}</td>
                  </tr>
                ) : uploadLogs.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No upload logs yet. Completed uploads will appear here.</td>
                  </tr>
                ) : (
                  uploadLogs.map((entry) => (
                    <tr key={entry.id}>
                      <td>{getUploadLabel(entry.upload_type)}</td>
                      <td>{formatDateTime(entry.uploaded_at)}</td>
                      <td>{entry.programme_code ?? 'All'}</td>
                      <td>{formatWarningsStatus(entry)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </article>

        <article className="card">
          <div className="section-header">
            <h2>Warning review</h2>
            <button type="button" className="button button-ghost" onClick={() => navigate('/admin/upload/warnings')}>
              All warnings {'->'}
            </button>
          </div>
          <ul className="warning-list">
            <li>Warnings are now read from persisted upload logs. Open the review page to load current rows.</li>
          </ul>
        </article>
      </section>
    </div>
  )
}
