import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { listProgrammes, type Programme } from '../../api/programmes'
import { uploadWorkbook } from '../../api/uploads'
import { IconCalendar, IconFile, IconGrid } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { UploadCard } from '../../components/UploadCard'
import { frontendConfig } from '../../config/frontendConfig'
import { useAppState } from '../../context/useAppState'
import type { UploadType } from '../../types/app'
import { buildMasterAdminTtfProgrammeOptions } from './adminUploadPageLogic'

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
  const [programmesLoading, setProgrammesLoading] = useState(true)
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
          setProgrammesError(error instanceof Error ? error.message : 'Unable to load programme catalogue.')
        }
      } finally {
        if (active) {
          setProgrammesLoading(false)
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

  const uploadOne = async (uploadType: UploadType, file: File) => {
    const response = await uploadWorkbook({
      uploadType,
      file,
      reportingPeriodId,
      programmeCode: selectedProgrammeCode,
      adminId: demoAdminId,
      adminProgrammes: demoAdminProgrammes,
      adminLevel: 'master',
    })

    addUploadResult({
      uploadType,
      response,
      filename: file.name,
      reportingPeriodId,
      reportingPeriodLabel,
      programmeCode: uploadType === 'ttf' ? selectedProgrammeCode : undefined,
    })

    return response
  }

  const formatPeriodOptionLabel = (label: string, startDate: string, endDate: string) => {
    const start = new Date(startDate)
    const end = new Date(endDate)
    if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) {
      return label
    }
    const rangeText = `${start.toLocaleDateString(undefined, {
      month: 'short',
      year: 'numeric',
    })} - ${end.toLocaleDateString(undefined, { month: 'short', year: 'numeric' })}`
    return `${label} (${rangeText})`
  }

  const hasSelectorOptions = reportingPeriods.length > 0
  const useManualReportingPeriodFallback =
    reportingPeriodsError !== null || (!reportingPeriodsLoading && reportingPeriods.length === 0)

  const reviewWarningsForUpload = (uploadType: UploadType) => {
    const latest = latestByType.get(uploadType)
    const params = new URLSearchParams({ mode: 'active', upload_type: uploadType })
    if (!latest) {
      if (uploadType === 'rdb' || uploadType === 'form_f1' || uploadType === 'ttf') {
        params.set('reporting_period_id', reportingPeriodId)
      }
      if (uploadType === 'ttf') {
        params.set('programme_code', selectedProgrammeCode)
      }
      navigate(`/admin/upload/warnings?${params.toString()}`)
      return
    }
    if (latest.reportingPeriodId) {
      params.set('reporting_period_id', latest.reportingPeriodId)
    }
    if (latest.programmeCode) {
      params.set('programme_code', latest.programmeCode)
    }
    navigate(`/admin/upload/warnings?${params.toString()}`)
  }

  return (
    <div className="page admin-upload-page">
      <PageHero
        title="Upload Files"
        subtitle="Master Admin - Source workbooks"
        meta={[
          { label: 'API base URL', value: frontendConfig.apiBaseUrl },
          {
            label: 'TTF programme coverage',
            value: programmesLoading
              ? 'Loading programme catalogue'
              : programmesError
                ? `Fallback: ${demoAdminProgrammes.join(', ')}`
                : `${ttfProgrammeOptions.length} programmes`,
          },
        ]}
      />

      <section className="card control-panel">
        <h2>Upload parameters</h2>
        <div className="form-grid">
          <label>
            Reporting period
            {hasSelectorOptions ? (
              <>
                <select value={reportingPeriodId} onChange={(event) => setReportingPeriodId(event.target.value)}>
                  {reportingPeriods.map((period) => (
                    <option key={period.id} value={period.id}>
                      {formatPeriodOptionLabel(period.label, period.startDate, period.endDate)}
                    </option>
                  ))}
                </select>
                <small>Selects the reporting_period_id sent for RDB, TTF, and FormF1 uploads.</small>
              </>
            ) : null}
            {reportingPeriodsLoading ? <small>Loading reporting periods...</small> : null}
            {useManualReportingPeriodFallback ? (
              <>
                <input
                  type="text"
                  value={reportingPeriodId}
                  onChange={(event) => setReportingPeriodId(event.target.value)}
                  placeholder="reporting_periods.id (UUID), required for RDB, TTF, FormF1"
                />
                <small>
                  Reporting-period list unavailable. Use manual UUID fallback.{' '}
                  <button type="button" className="button-link" onClick={() => void reloadReportingPeriods()}>
                    Retry loading list
                  </button>
                </small>
              </>
            ) : null}
            {reportingPeriodsError ? <small className="upload-validation-text">{reportingPeriodsError}</small> : null}
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
          reportingPeriodId={reportingPeriodId}
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
          reportingPeriodId={reportingPeriodId}
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
          reportingPeriodId={reportingPeriodId}
          onUpload={(file) => uploadOne('form_f1', file)}
          onReviewWarnings={() => reviewWarningsForUpload('form_f1')}
        />
      </section>
    </div>
  )
}
