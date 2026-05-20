import { useMemo, type ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadWorkbook } from '../../api/uploads'
import { IconCalendar, IconFile, IconGrid } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { UploadCard } from '../../components/UploadCard'
import { frontendConfig } from '../../config/frontendConfig'
import { useAppState } from '../../context/useAppState'
import type { UploadType } from '../../types/app'

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
    selectedProgrammeCode,
    setSelectedProgrammeCode,
    demoAdminId,
    demoAdminProgrammes,
    addUploadResult,
    uploadHistory,
  } = useAppState()

  const latestByType = useMemo(() => {
    const map = new Map<UploadType, (typeof uploadHistory)[number]>()
    uploadHistory.forEach((entry) => {
      if (!map.has(entry.uploadType)) {
        map.set(entry.uploadType, entry)
      }
    })
    return map
  }, [uploadHistory])

  const uploadOne = async (uploadType: UploadType, file: File) => {
    const response = await uploadWorkbook({
      uploadType,
      file,
      reportingPeriodId,
      programmeCode: selectedProgrammeCode,
      adminId: demoAdminId,
      adminProgrammes: demoAdminProgrammes,
    })

    addUploadResult({
      uploadType,
      response,
      reportingPeriodId,
      programmeCode: uploadType === 'ttf' ? selectedProgrammeCode : undefined,
    })

    return response
  }

  return (
    <div className="page">
      <PageHero
        title="Upload Files"
        subtitle="Master Admin - Source workbooks"
        meta={[
          { label: 'API base URL', value: frontendConfig.apiBaseUrl },
          { label: 'Admin programme scope', value: demoAdminProgrammes.join(', ') },
        ]}
      />

      <section className="card control-panel">
        <h2>Upload parameters</h2>
        <div className="form-grid">
          <label>
            Reporting period ID
            <input
              type="text"
              value={reportingPeriodId}
              onChange={(event) => setReportingPeriodId(event.target.value)}
              placeholder="reporting_periods.id (UUID), required for RDB, TTF, FormF1"
            />
            <small>
              Manual entry only in Phase 1. Use the exact `reporting_periods.id` value from backend data.
            </small>
          </label>
          <label>
            Programme code (TTF)
            <select
              value={selectedProgrammeCode}
              onChange={(event) => setSelectedProgrammeCode(event.target.value)}
            >
              {demoAdminProgrammes.map((programmeCode) => (
                <option key={programmeCode} value={programmeCode}>
                  {programmeCode}
                </option>
              ))}
            </select>
            <small>
              TTF upload checks this value against X-User-Programme scope. Bulk TTF upload is deferred; upload one
              programme at a time.
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
          onReviewWarnings={() => navigate('/admin/upload/warnings')}
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
          onReviewWarnings={() => navigate('/admin/upload/warnings')}
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
          onReviewWarnings={() => navigate('/admin/upload/warnings')}
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
          onReviewWarnings={() => navigate('/admin/upload/warnings')}
        />
      </section>
    </div>
  )
}
