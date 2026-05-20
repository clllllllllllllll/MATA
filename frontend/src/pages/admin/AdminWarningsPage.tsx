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
  return 'info' as const
}

export const AdminWarningsPage = () => {
  const navigate = useNavigate()
  const { warnings, updateWarningStatus, demoAdminProgrammes } = useAppState()
  const [selectedWarning, setSelectedWarning] = useState<NormalizedWarning | null>(null)
  const [uploadTypeFilter, setUploadTypeFilter] = useState<string>('all')
  const [severityFilter, setSeverityFilter] = useState<string>('all')
  const [statusFilter, setStatusFilter] = useState<string>('unresolved')
  const [programmeFilter, setProgrammeFilter] = useState<string>('all')
  const [searchTerm, setSearchTerm] = useState('')

  const programmeOptions = useMemo(
    () =>
      Array.from(
        new Set(
          [...demoAdminProgrammes, ...warnings
            .map((warning) => warning.programmeCode)
            .filter((item): item is string => Boolean(item && item.trim()))],
        ),
      ).sort(),
    [warnings, demoAdminProgrammes],
  )

  const unresolvedCount = useMemo(
    () => warnings.filter((item) => item.status === 'unresolved').length,
    [warnings],
  )

  const filteredWarnings = useMemo(() => {
    return warnings.filter((warning) => {
      const byUploadType = uploadTypeFilter === 'all' || warning.uploadType === uploadTypeFilter
      const bySeverity = severityFilter === 'all' || warning.severity === severityFilter
      const byStatus = statusFilter === 'all' || warning.status === statusFilter
      const byProgramme =
        programmeFilter === 'all' || warning.programmeCode === programmeFilter
      const bySearch =
        searchTerm.trim().length === 0 ||
        [
          warning.type,
          warning.message,
          warning.residentName,
          warning.mcr,
          warning.monthLabel,
          warning.sheetName,
          warning.filename,
          warning.reportingPeriodLabel,
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
          .includes(searchTerm.toLowerCase())

      return byUploadType && bySeverity && byStatus && byProgramme && bySearch
    })
  }, [warnings, uploadTypeFilter, severityFilter, statusFilter, programmeFilter, searchTerm])

  const clearFilters = () => {
    setUploadTypeFilter('all')
    setSeverityFilter('all')
    setStatusFilter('unresolved')
    setProgrammeFilter('all')
    setSearchTerm('')
  }

  const openRelatedConfig = (warning: NormalizedWarning) => {
    saveWarningContext(warning)
    const params = new URLSearchParams({
      warningId: warning.id,
      warningType: warning.type,
      mcr: warning.mcr ?? '',
      month: warning.monthLabel ?? '',
      postingCodes: warning.postingCodes?.join(',') ?? '',
    })
    navigate(`/admin/config/multi?${params.toString()}`, { state: { warningId: warning.id } })
  }

  return (
    <div className="page">
      <PageHero
        title="Warnings"
        subtitle={`${unresolvedCount} unresolved warning${unresolvedCount === 1 ? '' : 's'}`}
        meta={[{ label: 'Rows', value: String(filteredWarnings.length) }]}
      />

      <section className="inline-callout callout-info">
        Showing current warnings from the latest upload for each upload slot in this browser session.
      </section>

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
          Severity
          <select value={severityFilter} onChange={(event) => setSeverityFilter(event.target.value)}>
            <option value="all">All</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
        </label>
        <label>
          Status
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)}>
            <option value="unresolved">Unresolved</option>
            <option value="resolved">Resolved</option>
            <option value="dismissed">Dismissed</option>
            <option value="all">All</option>
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
        <button type="button" className="button button-ghost" onClick={clearFilters}>
          Clear filters
        </button>
      </section>

      <section className="table-wrap">
        <div className="table-scroll">
        <table className="table warnings-table">
          <colgroup>
            <col className="col-severity" />
            <col className="col-type" />
            <col className="col-upload" />
            <col className="col-resident" />
            <col className="col-mcr" />
            <col className="col-programme" />
            <col className="col-month" />
            <col className="col-source" />
            <col className="col-message" />
            <col className="col-status" />
          </colgroup>
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
                <td colSpan={10}>
                  {warnings.length === 0 ? 'No warnings to review.' : 'No warnings match the selected filters.'}
                </td>
              </tr>
            ) : (
              filteredWarnings.map((warning) => (
                <tr
                  key={warning.id}
                  className="table-clickable-row"
                  onClick={() => setSelectedWarning(warning)}
                >
                  <td className="cell-severity">
                    <StatusBadge
                      label={warning.severity.toUpperCase()}
                      tone={warningTone(warning.severity)}
                    />
                  </td>
                  <td className="cell-type">{warning.type}</td>
                  <td className="cell-upload">{warning.uploadLabel}</td>
                  <td className="cell-resident">{warning.residentName ?? '-'}</td>
                  <td className="cell-mcr">{warning.mcr ?? '-'}</td>
                  <td className="cell-programme">{warning.programmeCode ?? '-'}</td>
                  <td className="cell-month">{warning.monthLabel ?? '-'}</td>
                  <td className="cell-source">
                    {warning.sheetName || warning.rowNumber || warning.cellRef
                      ? `${warning.sheetName ?? '-'} / ${warning.rowNumber ?? '-'} / ${warning.cellRef ?? '-'}`
                      : '-'}
                  </td>
                  <td className="cell-message">{warning.message}</td>
                  <td className="cell-status">{warning.status}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
        </div>
      </section>

      <DetailDrawer
        title={selectedWarning ? `Warning: ${selectedWarning.type}` : 'Warning detail'}
        open={Boolean(selectedWarning)}
        onClose={() => setSelectedWarning(null)}
        footer={
          selectedWarning ? (
            <>
              {selectedWarning.type === 'unmatched_multi_posting' ? (
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => openRelatedConfig(selectedWarning)}
                >
                  Open Multi-Posting Rules →
                </button>
              ) : null}
              {selectedWarning.status !== 'resolved' ? (
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => {
                    updateWarningStatus(selectedWarning.id, 'resolved')
                    setSelectedWarning({ ...selectedWarning, status: 'resolved' })
                  }}
                >
                  Mark resolved
                </button>
              ) : null}
              {selectedWarning.status !== 'dismissed' ? (
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => {
                    updateWarningStatus(selectedWarning.id, 'dismissed')
                    setSelectedWarning({ ...selectedWarning, status: 'dismissed' })
                  }}
                >
                  Dismiss
                </button>
              ) : null}
              {selectedWarning.status !== 'unresolved' ? (
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={() => {
                    updateWarningStatus(selectedWarning.id, 'unresolved')
                    setSelectedWarning({ ...selectedWarning, status: 'unresolved' })
                  }}
                >
                  Reopen
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
              <h3>Subject</h3>
              <p>resident_name: {selectedWarning.residentName ?? '-'}</p>
              <p>mcr: {selectedWarning.mcr ?? '-'}</p>
              <p>programme_code: {selectedWarning.programmeCode ?? '-'}</p>
              <p>month: {selectedWarning.monthLabel ?? '-'}</p>
              <p>reporting_period: {selectedWarning.reportingPeriodLabel ?? selectedWarning.reportingPeriodId ?? '-'}</p>
              <p>file: {selectedWarning.filename ?? '-'}</p>
            </div>
            <div className="detail-block">
              <h3>Source traceability</h3>
              <p>sheet_name: {selectedWarning.sheetName ?? '-'}</p>
              <p>row_number: {selectedWarning.rowNumber ?? '-'}</p>
              <p>cell_ref: {selectedWarning.cellRef ?? '-'}</p>
              <p>upload_type: {selectedWarning.uploadType}</p>
            </div>
            {selectedWarning.suggestedAction ? (
              <div className="detail-block">
                <h3>Suggested action</h3>
                <p>{selectedWarning.suggestedAction}</p>
              </div>
            ) : null}
            <div className="detail-block">
              <h3>Developer details</h3>
              <pre className="raw-json">{JSON.stringify(selectedWarning.raw, null, 2)}</pre>
            </div>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
