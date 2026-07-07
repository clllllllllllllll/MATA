import { useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadWorkbook } from '../../api/uploads'
import { IconGrid } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { UploadCard } from '../../components/UploadCard'
import { useAuth } from '../../context/useAuth'
import { useAppState } from '../../context/useAppState'
import { formatReportingPeriodOptionLabel } from '../../utils/reportingPeriods'
import { buildPcTtfWarningsPath, resolvePcProgrammeScope } from './pcUploadTtfPageLogic'

const formatDateTime = (iso?: string | null) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : 'Not uploaded yet'

const latestLocalTtfUpload = (
  uploadHistory: ReturnType<typeof useAppState>['uploadHistory'],
  programmeCode: string,
) => uploadHistory.find((entry) => entry.uploadType === 'ttf' && entry.programmeCode === programmeCode)

export const PcUploadTtfPage = () => {
  const navigate = useNavigate()
  const { identity } = useAuth()
  const {
    reportingPeriodId,
    setReportingPeriodId,
    reportingPeriodLabel,
    reportingPeriods,
    reportingPeriodsLoading,
    reportingPeriodsError,
    reloadReportingPeriods,
    selectedProgrammeCode,
    setSelectedProgrammeCode,
    uploadHistory,
    addUploadResult,
  } = useAppState()

  const pcProgrammeScope = useMemo(
    () => (identity?.role === 'programme_pc' ? identity.programmeScope : []),
    [identity],
  )
  const pcAdminId = identity?.role === 'programme_pc' ? identity.subjectId : ''
  const programmeScope = useMemo(
    () => resolvePcProgrammeScope(pcProgrammeScope, selectedProgrammeCode),
    [pcProgrammeScope, selectedProgrammeCode],
  )
  const selectedPcProgrammeCode = programmeScope.selectedProgrammeCode
  const selectedPeriod = useMemo(
    () => reportingPeriods.find((period) => period.id === reportingPeriodId),
    [reportingPeriodId, reportingPeriods],
  )
  const activeReportingPeriodId =
    reportingPeriods.length > 0 && reportingPeriodId.trim().length > 0 ? reportingPeriodId : ''
  const localLatestTtfUpload = latestLocalTtfUpload(uploadHistory, selectedPcProgrammeCode)

  useEffect(() => {
    if (selectedPcProgrammeCode && selectedProgrammeCode !== selectedPcProgrammeCode) {
      setSelectedProgrammeCode(selectedPcProgrammeCode)
    }
  }, [selectedPcProgrammeCode, selectedProgrammeCode, setSelectedProgrammeCode])

  const reviewWarnings = (periodId = activeReportingPeriodId, programmeCode = selectedPcProgrammeCode) => {
    navigate(buildPcTtfWarningsPath({
      programmeCode,
      reportingPeriodId: periodId,
    }))
  }

  const uploadTtf = async (file: File) => {
    const response = await uploadWorkbook({
      uploadType: 'ttf',
      file,
      reportingPeriodId: activeReportingPeriodId,
      programmeCode: selectedPcProgrammeCode,
      adminId: pcAdminId,
      adminProgrammes: programmeScope.programmeScope,
      adminLevel: 'programme',
    })

    addUploadResult({
      uploadType: 'ttf',
      response,
      filename: file.name,
      reportingPeriodId: activeReportingPeriodId,
      reportingPeriodLabel: selectedPeriod?.label ?? reportingPeriodLabel,
      programmeCode: selectedPcProgrammeCode,
    })
    return response
  }

  return (
    <div className="page pc-upload-ttf-page">
      <PageHero
        title="Upload Teaching Target File"
        subtitle="PC - Teaching Target File upload"
      />

      <section className="pc-upload-layout">
        <div className="pc-upload-main-stack">
          <section className="card control-panel pc-upload-controls">
            <h2>Upload Parameters</h2>
            <div className="form-grid">
              <label>
                Programme
                {programmeScope.mode === 'locked' ? (
                  <input
                    type="text"
                    className="pc-programme-readonly-field"
                    value={programmeScope.selectedProgrammeLabel}
                    readOnly
                  />
                ) : null}
                {programmeScope.mode === 'select' ? (
                  <select
                    value={selectedPcProgrammeCode}
                    onChange={(event) => setSelectedProgrammeCode(event.target.value)}
                  >
                    {programmeScope.programmeOptions.map((programme) => (
                      <option key={programme.code} value={programme.code}>
                        {programme.label}
                      </option>
                    ))}
                  </select>
                ) : null}
                {programmeScope.mode === 'none' ? (
                  <span className="upload-validation-text">
                    No programme scope is available for this PC.
                  </span>
                ) : null}
              </label>

              <label>
                Reporting period
                {reportingPeriods.length > 0 ? (
                  <select value={reportingPeriodId} onChange={(event) => setReportingPeriodId(event.target.value)}>
                    {reportingPeriods.map((period) => (
                      <option key={period.id} value={period.id}>
                        {formatReportingPeriodOptionLabel(period)}
                      </option>
                    ))}
                  </select>
                ) : null}
                {reportingPeriodsLoading ? <small>Loading reporting periods...</small> : null}
                {!reportingPeriodsLoading && reportingPeriods.length === 0 ? (
                  <small className="upload-validation-text">
                    No reporting period is available. Upload is disabled until a period can be selected.
                  </small>
                ) : null}
                {reportingPeriodsError ? (
                  <small className="upload-validation-text">
                    {reportingPeriodsError}{' '}
                    <button type="button" className="button-link" onClick={() => void reloadReportingPeriods()}>
                      Retry
                    </button>
                  </small>
                ) : null}
              </label>
            </div>
          </section>

          <UploadCard
            icon={<IconGrid size={18} />}
            title="Teaching Target File"
            lastUploadedText={localLatestTtfUpload ? formatDateTime(localLatestTtfUpload.uploadedAtIso) : undefined}
            accept=".xlsx"
            requiresReportingPeriod
            requiresProgramme
            reportingPeriodId={activeReportingPeriodId}
            programmeCode={selectedPcProgrammeCode}
            onUpload={uploadTtf}
            onReviewWarnings={() => reviewWarnings()}
          />
        </div>
      </section>
    </div>
  )
}
