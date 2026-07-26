import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { listProgrammes, type Programme } from '../../api/programmes'
import { uploadWorkbook } from '../../api/uploads'
import { IconCalendar, IconFile, IconGrid } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { UploadCard } from '../../components/UploadCard'
import { useAppState } from '../../context/useAppState'
import type { UploadType } from '../../types/app'
import { formatReportingPeriodOptionLabel } from '../../utils/reportingPeriods'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'
import {
  buildMasterAdminTtfProgrammeOptions,
  buildReviewWarningsPathForUploadSlot,
  resolveAdminUploadReportingPeriod,
  submitAdminUpload,
} from './adminUploadPageLogic'

const acceptedByType: Record<UploadType, string> = {
  public_holidays: '.xlsx,.csv',
  rdb: '.xlsx',
  ttf: '.xlsx',
  form_f1: '.xlsx',
}

const sourceIconByType: Record<UploadType, ReactNode> = {
  public_holidays: <IconCalendar size={18} />,
  rdb: <IconFile size={18} />,
  ttf: <IconGrid size={18} />,
  form_f1: <IconFile size={18} />,
}

const getStatusTone = (uploadedAtIso?: string) => {
  if (!uploadedAtIso) {
    return { label: 'Missing', tone: 'critical' as const }
  }

  const ageInDays = (Date.now() - new Date(uploadedAtIso).getTime()) / (1000 * 60 * 60 * 24)
  if (ageInDays > 30) {
    return { label: 'Stale', tone: 'warning' as const }
  }
  return { label: 'Current', tone: 'success' as const }
}

const toDisplayStatus = (uploadedAtIso?: string) => {
  const status = getStatusTone(uploadedAtIso)
  return status.label === 'Current' ? undefined : status
}

const formatDateTime = (iso?: string) =>
  iso
    ? new Date(iso).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
      })
    : 'Not uploaded yet'

export const AdminUploadPage = () => {
  const navigate = useNavigate()
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
    demoAdminId,
    demoAdminProgrammes,
    addUploadResult,
    uploadHistory,
  } = useAppState()
  const [programmeCatalogue, setProgrammeCatalogue] = useState<Programme[]>([])
  const [programmesError, setProgrammesError] = useState<string | null>(null)

  const latestByType = useMemo(() => {
    const map = new Map<UploadType, (typeof uploadHistory)[number]>()
    uploadHistory.forEach((entry) => {
      if (!map.has(entry.uploadType)) {
        map.set(entry.uploadType, entry)
      }
    })
    return map
  }, [uploadHistory])
  const ttfProgrammeOptions = useMemo(
    () => buildMasterAdminTtfProgrammeOptions(programmeCatalogue, demoAdminProgrammes),
    [demoAdminProgrammes, programmeCatalogue],
  )

  useEffect(() => {
    let active = true
    ;(async () => {
      try {
        const programmes = await listProgrammes({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel: 'master',
        })
        if (active) {
          setProgrammeCatalogue(programmes)
        }
      } catch (error) {
        if (active) {
          setProgrammeCatalogue([])
          setProgrammesError(formatUserFacingApiError(error, {
            fallbackMessage: 'Unable to load programme catalogue.',
          }))
        }
      }
    })()

    return () => {
      active = false
    }
  }, [demoAdminId, demoAdminProgrammes])

  useEffect(() => {
    if (
      ttfProgrammeOptions.length > 0 &&
      !ttfProgrammeOptions.some((programme) => programme.code === selectedProgrammeCode)
    ) {
      setSelectedProgrammeCode(ttfProgrammeOptions[0].code)
    }
  }, [selectedProgrammeCode, setSelectedProgrammeCode, ttfProgrammeOptions])

  const hasSelectorOptions = reportingPeriods.length > 0
  const reportingPeriodSelection = useMemo(
    () => resolveAdminUploadReportingPeriod(reportingPeriods, reportingPeriodId),
    [reportingPeriodId, reportingPeriods],
  )
  const selectedReportingPeriodId = reportingPeriodSelection.reportingPeriodId

  const uploadOne = async (uploadType: UploadType, file: File) => {
    const submitted = await submitAdminUpload({
      uploadType,
      file,
      reportingPeriod: reportingPeriodSelection,
      programmeCode: selectedProgrammeCode,
      adminId: demoAdminId,
      adminProgrammes: demoAdminProgrammes,
      adminLevel: 'master',
    }, uploadWorkbook)
    if (!submitted) {
      throw new Error(
        reportingPeriodSelection.validationMessage
          ?? 'Select a programme code before uploading.',
      )
    }

    addUploadResult({
      uploadType,
      response: submitted.response,
      filename: file.name,
      reportingPeriodId: submitted.request.reportingPeriodId,
      reportingPeriodLabel: reportingPeriodSelection.period?.label ?? reportingPeriodLabel,
      programmeCode: uploadType === 'ttf' ? selectedProgrammeCode : undefined,
    })

    return submitted.response
  }

  const reviewWarningsForUpload = (uploadType: UploadType) => {
    const latest = latestByType.get(uploadType)
    navigate(buildReviewWarningsPathForUploadSlot({
      uploadType,
      selectedReportingPeriodId,
      selectedProgrammeCode,
      latestUpload: latest
        ? {
            reportingPeriodId: latest.reportingPeriodId,
            programmeCode: latest.programmeCode,
          }
        : undefined,
    }))
  }

  return (
    <div className="page admin-upload-page">
      <PageHero
        title="Upload Files"
        subtitle="Master Admin - Source workbooks"
      />

      <section className="card control-panel">
        <h2>Upload parameters</h2>
        <div className="form-grid">
          <label>
            Reporting period
            {hasSelectorOptions ? (
              <>
                <select value={reportingPeriodId} onChange={(event) => setReportingPeriodId(event.target.value)}>
                  <option value="">Select a reporting period</option>
                  {reportingPeriods.map((period) => (
                    <option key={period.id} value={period.id}>
                      {formatReportingPeriodOptionLabel(period)}
                    </option>
                  ))}
                </select>
                <small>Used to scope RDB, TTF, and FormF1 uploads.</small>
              </>
            ) : null}
            {reportingPeriodsLoading ? <small>Loading reporting periods...</small> : null}
            {!reportingPeriodsLoading && !hasSelectorOptions ? (
              <small className="upload-validation-text">
                Reporting period unavailable.{' '}
                <button type="button" className="button-link" onClick={() => void reloadReportingPeriods()}>
                  Retry loading list
                </button>
              </small>
            ) : null}
            {reportingPeriodsError && hasSelectorOptions ? (
              <small className="upload-validation-text">Reporting period list could not be refreshed.</small>
            ) : null}
          </label>
          <label>
            Programme code (TTF)
            <select
              value={selectedProgrammeCode}
              onChange={(event) => setSelectedProgrammeCode(event.target.value)}
            >
              {ttfProgrammeOptions.map((programme) => (
                <option key={programme.code} value={programme.code}>
                  {programme.label}
                </option>
              ))}
            </select>
            <small>
              {programmesError
                ? `${programmesError} Using configured fallback. Upload one TTF for one explicit programme at a time.`
                : 'Master Admin can upload one TTF for any valid programme at a time.'}
            </small>
          </label>
        </div>
      </section>

      <section className="upload-grid">
        <UploadCard
          icon={sourceIconByType.public_holidays}
          title="Academic Calendar / Public Holidays"
          sourceStatus={toDisplayStatus(latestByType.get('public_holidays')?.uploadedAtIso)}
          lastUploadedText={formatDateTime(latestByType.get('public_holidays')?.uploadedAtIso)}
          accept={acceptedByType.public_holidays}
          onUpload={(file) => uploadOne('public_holidays', file)}
          onReviewWarnings={() => reviewWarningsForUpload('public_holidays')}
        />

        <UploadCard
          icon={sourceIconByType.rdb}
          title="RDB Posting Schedule"
          sourceStatus={toDisplayStatus(latestByType.get('rdb')?.uploadedAtIso)}
          lastUploadedText={formatDateTime(latestByType.get('rdb')?.uploadedAtIso)}
          accept={acceptedByType.rdb}
          requiresReportingPeriod
          reportingPeriodId={selectedReportingPeriodId}
          reportingPeriodValidationMessage={reportingPeriodSelection.validationMessage}
          onUpload={(file) => uploadOne('rdb', file)}
          onReviewWarnings={() => reviewWarningsForUpload('rdb')}
        />

        <UploadCard
          icon={sourceIconByType.ttf}
          title="Teaching Target File"
          sourceStatus={toDisplayStatus(latestByType.get('ttf')?.uploadedAtIso)}
          lastUploadedText={formatDateTime(latestByType.get('ttf')?.uploadedAtIso)}
          accept={acceptedByType.ttf}
          requiresReportingPeriod
          requiresProgramme
          reportingPeriodId={selectedReportingPeriodId}
          reportingPeriodValidationMessage={reportingPeriodSelection.validationMessage}
          programmeCode={selectedProgrammeCode}
          onUpload={(file) => uploadOne('ttf', file)}
          onReviewWarnings={() => reviewWarningsForUpload('ttf')}
        />

        <UploadCard
          icon={sourceIconByType.form_f1}
          title="FormF1"
          sourceStatus={toDisplayStatus(latestByType.get('form_f1')?.uploadedAtIso)}
          lastUploadedText={formatDateTime(latestByType.get('form_f1')?.uploadedAtIso)}
          accept={acceptedByType.form_f1}
          requiresReportingPeriod
          reportingPeriodId={selectedReportingPeriodId}
          reportingPeriodValidationMessage={reportingPeriodSelection.validationMessage}
          onUpload={(file) => uploadOne('form_f1', file)}
          onReviewWarnings={() => reviewWarningsForUpload('form_f1')}
        />
      </section>
    </div>
  )
}
