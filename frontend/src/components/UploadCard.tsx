import { useEffect, useMemo, useRef, useState, type DragEventHandler, type ReactNode } from 'react'
import { StatusBadge } from './StatusBadge'
import { getSummaryCounts, getWarningsCount } from '../utils/warnings'
import { ApiRequestError } from '../api/http'
import { IconCheck, IconWarn } from './icons'

interface UploadCardProps {
  icon: ReactNode
  title: string
  subtitle?: string
  lastUploadedText?: string
  sourceStatus?: {
    label: string
    tone: 'success' | 'warning' | 'critical' | 'info' | 'neutral'
  }
  accept: string
  reportingPeriodId?: string
  programmeCode?: string
  requiresReportingPeriod?: boolean
  requiresProgramme?: boolean
  onUpload: (file: File) => Promise<Record<string, unknown>>
  onReviewWarnings?: () => void
}

export const UploadCard = ({
  icon,
  title,
  subtitle,
  lastUploadedText,
  sourceStatus,
  accept,
  reportingPeriodId,
  programmeCode,
  requiresReportingPeriod = false,
  requiresProgramme = false,
  onUpload,
  onReviewWarnings,
}: UploadCardProps) => {
  const [file, setFile] = useState<File | null>(null)
  const [status, setStatus] = useState<
    'idle' | 'selected' | 'uploading' | 'parsing' | 'success' | 'error'
  >('idle')
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [errorDetails, setErrorDetails] = useState<unknown>(null)
  const [response, setResponse] = useState<Record<string, unknown> | null>(null)
  const [isDraggingFile, setIsDraggingFile] = useState(false)
  const [uploadProgressPercent, setUploadProgressPercent] = useState(0)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const dragDepthRef = useRef(0)

  const isUploadDisabled =
    !file ||
    status === 'uploading' ||
    status === 'parsing' ||
    (requiresReportingPeriod && !(reportingPeriodId && reportingPeriodId.trim().length > 0)) ||
    (requiresProgramme && !(programmeCode && programmeCode.trim().length > 0))

  const summary = useMemo(() => (response ? getSummaryCounts(response) : null), [response])
  const warningsCount = response ? getWarningsCount(response) : 0
  const createdCount = summary?.created
  const updatedCount = summary?.updated
  const isSuspiciousZeroResult =
    status === 'success' && createdCount === 0 && updatedCount === 0 && warningsCount === 0
  const missingReportingPeriod =
    requiresReportingPeriod && !(reportingPeriodId && reportingPeriodId.trim().length > 0)
  const missingProgrammeCode =
    requiresProgramme && !(programmeCode && programmeCode.trim().length > 0)

  useEffect(() => {
    if (status !== 'uploading') {
      return
    }

    const timer = window.setInterval(() => {
      setUploadProgressPercent((prev) => {
        if (prev >= 88) {
          return prev
        }
        return prev + 6
      })
    }, 180)

    return () => window.clearInterval(timer)
  }, [status])

  const validateFile = (candidate: File): string | null => {
    const acceptedExtensions = accept
      .split(',')
      .map((entry) => entry.trim().toLowerCase())
      .filter(Boolean)

    const fileName = candidate.name.toLowerCase()
    const isAllowed = acceptedExtensions.some((extension) => fileName.endsWith(extension))
    return isAllowed
      ? null
      : `Invalid file type. Allowed: ${acceptedExtensions.join(', ')}`
  }

  const handleFileChange = (selected: File | null) => {
    if (!selected) {
      setFile(null)
      setStatus('idle')
      setErrorMessage(null)
      setErrorDetails(null)
      setUploadProgressPercent(0)
      return
    }
    const validationError = validateFile(selected)
    if (validationError) {
      setErrorMessage(validationError)
      setErrorDetails(null)
      setStatus('error')
      setFile(null)
      return
    }
    setFile(selected)
    setStatus(selected ? 'selected' : 'idle')
    setErrorMessage(null)
    setErrorDetails(null)
  }

  const onDragEnter: DragEventHandler<HTMLLabelElement> = (event) => {
    event.preventDefault()
    event.stopPropagation()
    dragDepthRef.current += 1
    setIsDraggingFile(true)
  }

  const onDragOver: DragEventHandler<HTMLLabelElement> = (event) => {
    event.preventDefault()
    event.stopPropagation()
    event.dataTransfer.dropEffect = 'copy'
    setIsDraggingFile(true)
  }

  const onDragLeave: DragEventHandler<HTMLLabelElement> = (event) => {
    event.preventDefault()
    event.stopPropagation()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) {
      setIsDraggingFile(false)
    }
  }

  const onDrop: DragEventHandler<HTMLLabelElement> = (event) => {
    event.preventDefault()
    event.stopPropagation()
    dragDepthRef.current = 0
    setIsDraggingFile(false)
    const droppedFile = event.dataTransfer.files?.[0] ?? null
    handleFileChange(droppedFile)
  }

  const handleUpload = async () => {
    if (!file) {
      return
    }
    setStatus('uploading')
    setUploadProgressPercent(12)
    setErrorMessage(null)
    setErrorDetails(null)

    try {
      const result = await onUpload(file)
      setResponse(result)
      setUploadProgressPercent(100)
      setStatus('success')
    } catch (error) {
      let message = error instanceof Error ? error.message : 'Upload failed. Please try again.'
      let details: unknown = null

      if (error instanceof ApiRequestError) {
        details = error.details
        if (error.status === 401 || error.status === 403) {
          message = 'Upload was rejected because the demo admin is not authorised for this action.'
        } else if (error.status === 422) {
          message =
            'Upload failed validation or parser checks. Check the workbook type, required fields, and reporting period.'
        } else if (error.status === 409) {
          message = 'Another upload is already running for this scope. Try again shortly.'
        } else if (error.status && error.status >= 500) {
          message = 'The server hit an error while processing this upload.'
        } else if (error.isNetworkError) {
          message = 'Could not reach the backend. Check Docker services and try again.'
        }
      }

      setErrorMessage(message)
      setErrorDetails(details)
      setUploadProgressPercent(0)
      setStatus('error')
    }
  }

  const clearFile = () => {
    setFile(null)
    setStatus('idle')
    setErrorMessage(null)
    setErrorDetails(null)
    setUploadProgressPercent(0)
    if (inputRef.current) {
      inputRef.current.value = ''
    }
  }

  const formatFileSize = (bytes: number): string => {
    if (bytes < 1024) {
      return `${bytes} B`
    }
    const kb = bytes / 1024
    if (kb < 1024) {
      return `${kb.toFixed(1)} KB`
    }
    return `${(kb / 1024).toFixed(2)} MB`
  }

  const isLoadingState = status === 'uploading' || status === 'parsing'
  const isTerminalState = status === 'success' || status === 'error'

  return (
    <article className="card upload-card">
      <header className="upload-card-h upload-card-header">
        <div className="icon-wrap upload-card-icon">{icon}</div>
        <div className="upload-card-title-block">
          <div className="upload-card-title-row">
            <h2>{title}</h2>
            {sourceStatus ? (
              <StatusBadge label={sourceStatus.label} tone={sourceStatus.tone} />
            ) : null}
          </div>
          <p className="source-subtext">{lastUploadedText ?? subtitle}</p>
          {!lastUploadedText && subtitle ? <p>{subtitle}</p> : null}
        </div>
      </header>

      <div className="upload-card-content">
        {!isLoadingState && !isTerminalState ? (
          <>
            <label
              className={`file-dropzone ${file ? 'is-selected' : ''} ${isDraggingFile ? 'is-dragging' : ''}`}
              htmlFor={`upload-${title}`}
              onDragEnter={onDragEnter}
              onDragOver={onDragOver}
              onDragLeave={onDragLeave}
              onDrop={onDrop}
            >
              <input
                id={`upload-${title}`}
                ref={inputRef}
                type="file"
                accept={accept}
                onChange={(event) => handleFileChange(event.target.files?.[0] ?? null)}
              />
              {!file ? (
                <span>
                  Drop file here or <strong>Browse</strong>
                </span>
              ) : (
                <div className="selected-file-chip">
                  <span>
                    {file.name} ({formatFileSize(file.size)})
                  </span>
                  <button type="button" className="button button-ghost danger" onClick={clearFile}>
                    Remove
                  </button>
                </div>
              )}
            </label>

            {missingReportingPeriod || missingProgrammeCode ? (
              <div className="upload-validation-slot" aria-live="polite">
                {missingReportingPeriod ? (
                  <small className="upload-validation-text">
                    Reporting period ID is required and must be a `reporting_periods.id` value for this upload.
                  </small>
                ) : null}
                {missingProgrammeCode ? (
                  <small className="upload-validation-text">
                    Programme code is required for TTF and must be one programme within your configured scope.
                  </small>
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}

        {isLoadingState ? (
          <div className="upload-progress-card upload-state-panel">
            <div className="upload-progress-row">
              <span>{status === 'parsing' ? 'Parsing...' : 'Uploading...'}</span>
              <span>{uploadProgressPercent}%</span>
            </div>
            <div
              className="upload-progress-track"
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={uploadProgressPercent}
            >
              <div className="upload-progress-fill" style={{ width: `${uploadProgressPercent}%` }} />
            </div>
          </div>
        ) : null}

        {!isLoadingState && !isTerminalState ? (
          <div className="upload-card-actions">
            <button type="button" className="button button-primary" disabled={isUploadDisabled} onClick={handleUpload}>
              Upload
            </button>
          </div>
        ) : null}

        {status === 'error' && errorMessage ? (
          <div className="inline-callout callout-error upload-result-card upload-state-panel">
            <div className="upload-result-title">
              <IconWarn size={16} />
              <strong>Upload failed</strong>
            </div>
            <p className="upload-result-message">{errorMessage}</p>
            {errorDetails ? <p className="inline-muted">Additional error context was captured for review.</p> : null}
            <div className="result-actions">
              <button
                type="button"
                className="button button-secondary"
                onClick={clearFile}
              >
                Upload another
              </button>
            </div>
          </div>
        ) : null}

        {status === 'success' && response ? (
          <div
            className={`inline-callout upload-result-card ${
              isSuspiciousZeroResult ? 'callout-warning' : 'callout-success'
            } upload-state-panel`}
          >
            <div className="upload-result-title">
              {isSuspiciousZeroResult ? <IconWarn size={16} /> : <IconCheck size={16} />}
              <strong>{isSuspiciousZeroResult ? 'Upload completed with no rows' : 'Upload successful'}</strong>
            </div>
            <div className="upload-summary-metrics upload-summary-metrics-inline">
              <span>
                <strong>{createdCount ?? 0}</strong> created
              </span>
              <span>
                <strong>{updatedCount ?? 'N/A'}</strong> updated
              </span>
              <span>
                <strong>{summary?.warnings ?? 0}</strong> warnings
              </span>
            </div>
            {isSuspiciousZeroResult ? (
              <p className="upload-result-message">
                No rows were created or updated. Check that the correct workbook was uploaded for this slot.
              </p>
            ) : null}
            <div className="result-actions">
              <button type="button" className="button button-ghost" onClick={clearFile}>
                Upload another
              </button>
              {!isSuspiciousZeroResult && warningsCount > 0 ? (
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={onReviewWarnings}
                >
                  Review warnings &rarr;
                </button>
              ) : null}
            </div>
          </div>
        ) : null}
      </div>
    </article>
  )
}
