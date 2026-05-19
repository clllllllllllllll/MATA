import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { DetailDrawer } from '../../components/DetailDrawer'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAppState } from '../../context/useAppState'
import { saveWarningContext } from '../../utils/storage'
import type { NormalizedWarning } from '../../types/upload'

const warningTone = (severity: NormalizedWarning['severity']) => {
  if (severity === 'critical') {
    return 'critical' as const
  }
  if (severity === 'warning') {
    return 'warning' as const
  }
  if (severity === 'resolved') {
    return 'success' as const
  }
  return 'info' as const
}

export const AdminWarningsPage = () => {
  const navigate = useNavigate()
  const { warnings, markWarningResolved } = useAppState()
  const [selectedWarning, setSelectedWarning] = useState<NormalizedWarning | null>(null)
  const [uploadTypeFilter, setUploadTypeFilter] = useState<string>('all')
  const [programmeFilter, setProgrammeFilter] = useState<string>('all')
  const [searchTerm, setSearchTerm] = useState('')

  const programmeOptions = useMemo(
    () =>
      Array.from(
        new Set(
          warnings
            .map((warning) => warning.programmeCode)
            .filter((item): item is string => Boolean(item && item.trim())),
        ),
      ).sort(),
    [warnings],
  )

  const filteredWarnings = useMemo(() => {
    return warnings.filter((warning) => {
      const byUploadType = uploadTypeFilter === 'all' || warning.uploadType === uploadTypeFilter
      const byProgramme =
        programmeFilter === 'all' || warning.programmeCode === programmeFilter
      const bySearch =
        searchTerm.trim().length === 0 ||
        [
          warning.warningType,
          warning.message,
          warning.residentName,
          warning.mcr,
          warning.monthLabel,
          warning.sheetName,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(searchTerm.toLowerCase())

      return byUploadType && byProgramme && bySearch
    })
  }, [warnings, uploadTypeFilter, programmeFilter, searchTerm])

  const openRelatedConfig = (warning: NormalizedWarning) => {
    saveWarningContext(warning)
    navigate('/admin/config/multi', { state: { warningId: warning.id } })
  }

  return (
    <div className="page">
      <PageHero
        title="Warning Review"
        subtitle="Master Admin - Aggregated warnings from latest upload responses"
        meta={[{ label: 'Rows', value: String(filteredWarnings.length) }]}
      />

      <section className="card filter-bar">
        <label>
          Upload type
          <select
            value={uploadTypeFilter}
            onChange={(event) => setUploadTypeFilter(event.target.value)}
          >
            <option value="all">All</option>
            <option value="public_holidays">Public Holidays</option>
            <option value="rdb">RDB</option>
            <option value="ttf">TTF</option>
            <option value="form_f1">FormF1</option>
          </select>
        </label>
        <label>
          Programme
          <select
            value={programmeFilter}
            onChange={(event) => setProgrammeFilter(event.target.value)}
          >
            <option value="all">All</option>
            {programmeOptions.map((programmeCode) => (
              <option key={programmeCode} value={programmeCode}>
                {programmeCode}
              </option>
            ))}
          </select>
        </label>
        <label>
          Warning search
          <input
            type="search"
            value={searchTerm}
            onChange={(event) => setSearchTerm(event.target.value)}
            placeholder="Type, resident, MCR, message..."
          />
        </label>
      </section>

      <section className="table-wrap">
        <div className="table-scroll">
        <table className="table">
          <thead>
            <tr>
              <th>Severity</th>
              <th>Type</th>
              <th>Upload</th>
              <th>Resident</th>
              <th>MCR</th>
              <th>Programme</th>
              <th>Month</th>
              <th>Source</th>
              <th>Message</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {filteredWarnings.length === 0 ? (
              <tr>
                <td colSpan={10}>No warnings match the selected filters.</td>
              </tr>
            ) : (
              filteredWarnings.map((warning) => (
                <tr
                  key={warning.id}
                  className="table-clickable-row"
                  onClick={() => setSelectedWarning(warning)}
                >
                  <td>
                    <StatusBadge
                      label={warning.severity.toUpperCase()}
                      tone={warningTone(warning.severity)}
                    />
                  </td>
                  <td>{warning.warningType}</td>
                  <td>{warning.uploadLabel}</td>
                  <td>{warning.residentName ?? '-'}</td>
                  <td>{warning.mcr ?? '-'}</td>
                  <td>{warning.programmeCode ?? '-'}</td>
                  <td>{warning.monthLabel ?? '-'}</td>
                  <td>
                    {warning.sheetName || warning.rowNumber || warning.cellRef
                      ? `${warning.sheetName ?? '-'} / ${warning.rowNumber ?? '-'} / ${warning.cellRef ?? '-'}`
                      : '-'}
                  </td>
                  <td>{warning.message}</td>
                  <td>{warning.status}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        </div>
      </section>

      <DetailDrawer
        title={selectedWarning ? `Warning: ${selectedWarning.warningType}` : 'Warning detail'}
        open={Boolean(selectedWarning)}
        onClose={() => setSelectedWarning(null)}
        footer={
          selectedWarning ? (
            <>
              {selectedWarning.warningType === 'unmatched_multi_posting' ? (
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => openRelatedConfig(selectedWarning)}
                >
                  Open related config
                </button>
              ) : null}
              {selectedWarning.status !== 'resolved' ? (
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => {
                    markWarningResolved(selectedWarning.id)
                    setSelectedWarning({ ...selectedWarning, status: 'resolved' })
                  }}
                >
                  Mark resolved
                </button>
              ) : null}
            </>
          ) : null
        }
      >
        {selectedWarning ? (
          <div className="warning-detail">
            <div className="detail-block">
              <h3>Summary</h3>
              <p>{selectedWarning.message}</p>
            </div>
            <div className="detail-block">
              <h3>Source traceability</h3>
              <p>sheet_name: {selectedWarning.sheetName ?? '-'}</p>
              <p>row_number: {selectedWarning.rowNumber ?? '-'}</p>
              <p>cell_ref: {selectedWarning.cellRef ?? '-'}</p>
              <p>upload_type: {selectedWarning.uploadType}</p>
            </div>
            <div className="detail-block">
              <h3>Raw warning JSON</h3>
              <pre className="raw-json">{JSON.stringify(selectedWarning.raw, null, 2)}</pre>
            </div>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
