import { useMemo, useRef, useState, type DragEventHandler, type ReactNode } from 'react'
import { StatusBadge } from './StatusBadge'
import { getSummaryCounts, getWarningsCount } from '../utils/warnings'

interface UploadCardProps {
  icon: ReactNode
  title: string
  subtitle: string
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
  const [response, setResponse] = useState<Record<string, unknown> | null>(null)
  const [showRawJson, setShowRawJson] = useState(false)
  const [isDraggingFile, setIsDraggingFile] = useState(false)
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
      return
    }
    const validationError = validateFile(selected)
    if (validationError) {
      setErrorMessage(validationError)
      setStatus('error')
      setFile(null)
      return
    }
    setFile(selected)
    setStatus(selected ? 'selected' : 'idle')
    setErrorMessage(null)
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
    setErrorMessage(null)

    try {
      const result = await onUpload(file)
      setStatus('parsing')
      setTimeout(() => {
        setResponse(result)
        setStatus('success')
      }, 600)
    } catch (error) {
      const message =
        error instanceof Error ? error.message : 'Upload failed. Please try again.'
      setErrorMessage(message)
      setStatus('error')
    }
  }

  const clearFile = () => {
    setFile(null)
    setStatus('idle')
    setErrorMessage(null)
    if (inputRef.current) {
      inputRef.current.value = ''
    }
  }

  return (
    <article className="card upload-card">
      <header className="upload-card-h upload-card-header">
        <div className="icon-wrap upload-card-icon">{icon}</div>
        <div className="upload-card-title-block" style={{ flex: 1 }}>
          <div className="upload-card-title-row">
            <h2>{title}</h2>
            {sourceStatus ? (
              <StatusBadge label={sourceStatus.label} tone={sourceStatus.tone} />
            ) : null}
          </div>
          <p className="source-subtext">{lastUploadedText ?? subtitle}</p>
          {lastUploadedText ? <p>{subtitle}</p> : null}
        </div>
      </header>

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
            <span>{file.name}</span>
            <button type="button" className="button button-ghost danger" onClick={clearFile}>
              Remove
            </button>
          </div>
        )}
      </label>

      <div className="upload-card-actions">
        <button type="button" className="button button-primary" disabled={isUploadDisabled} onClick={handleUpload}>
          {status === 'uploading' || status === 'parsing' ? 'Uploading...' : 'Upload'}
        </button>
        {status === 'uploading' || status === 'parsing' ? <span className="inline-muted">Parser running...</span> : null}
      </div>

      {status === 'error' && errorMessage ? (
        <div className="inline-callout callout-error">
          <strong>Upload failed</strong>
          <p>{errorMessage}</p>
        </div>
      ) : null}

      {status === 'success' && response ? (
        <div className="inline-callout callout-success">
          <div className="upload-summary-row">
            <strong>Upload complete</strong>
            <span>{warningsCount} warning(s)</span>
          </div>
          <p>
            Created: {summary?.created ?? 'n/a'} - Updated: {summary?.updated ?? 'n/a'} -
            Warnings: {summary?.warnings ?? 0}
          </p>
          <div className="result-actions">
            <button
              type="button"
              className="button button-ghost"
              onClick={() => setShowRawJson((prev) => !prev)}
            >
              {showRawJson ? 'Hide raw response' : 'View raw response'}
            </button>
            {warningsCount > 0 ? (
              <button
                type="button"
                className="button button-secondary"
                onClick={onReviewWarnings}
              >
                Review warnings
              </button>
            ) : null}
          </div>
          {showRawJson ? (
            <pre className="raw-json">{JSON.stringify(response, null, 2)}</pre>
          ) : null}
        </div>
      ) : null}
    </article>
  )
}
