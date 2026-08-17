import type {
  PcResidentAttendanceSourceFilter,
  PcResidentAttendanceStatus,
} from '../../api/pcResidentAttendance'

export const pcResidentAttendanceOverviewPath = '/pc/resident-attendance'

export const pcResidentAttendanceDetailPath = (residentId: string): string =>
  `/pc/residents/${encodeURIComponent(residentId)}/attendance`

export const displayCurrentPosting = (posting: {
  currentPostingCode?: string | null
  currentPostingLabel?: string | null
}): string =>
  posting.currentPostingLabel?.trim()
  || posting.currentPostingCode?.trim()
  || 'No current posting'

export const displayAttendancePosting = (posting: {
  postingCode?: string | null
  postingLabel?: string | null
}): string => posting.postingLabel?.trim() || posting.postingCode?.trim() || '-'

export const attendanceSourceLabel = (source: string): string => {
  switch (source.trim().toLowerCase()) {
    case 'department_secretary':
    case 'department secretary':
    case 'secretary':
    case 'secretary_event':
      return 'Department Secretary'
    case 'programme_pc':
    case 'programme pc':
      return 'PC'
    case 'adhoc':
    case 'ad-hoc':
      return 'Ad-hoc'
    default:
      return source.trim() || 'Unknown'
  }
}

export const attendanceSourceFilterLabel = (
  source: PcResidentAttendanceSourceFilter,
): string => attendanceSourceLabel(source)

export const attendanceSourceTone = (
  source: string,
): 'info' | 'warning' | 'neutral' => {
  const label = attendanceSourceLabel(source)
  if (label === 'PC') {
    return 'info'
  }
  if (label === 'Ad-hoc') {
    return 'warning'
  }
  return 'neutral'
}

export const attendanceStatusLabel = (status: string): string => {
  switch (status.trim().toLowerCase()) {
    case 'submitted':
      return 'Submitted'
    case 'flagged':
      return 'Flagged'
    case 'removed':
      return 'Removed'
    default:
      return status.trim() || 'Unknown'
  }
}

export const attendanceStatusFilterLabel = (
  status: PcResidentAttendanceStatus,
): string => attendanceStatusLabel(status)

export const attendanceStatusTone = (
  status: string,
): 'success' | 'warning' | 'neutral' => {
  switch (status.trim().toLowerCase()) {
    case 'submitted':
      return 'success'
    case 'flagged':
      return 'warning'
    default:
      return 'neutral'
  }
}

export const formatAttendanceDate = (value?: string | null): string => {
  if (!value) {
    return '-'
  }
  const parsed = new Date(`${value.slice(0, 10)}T00:00:00Z`)
  if (Number.isNaN(parsed.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat('en-SG', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(parsed)
}

export const formatAttendanceTime = (value?: string | null): string => {
  if (!value) {
    return '-'
  }
  const [hourText, minuteText] = value.split(':')
  const hour = Number(hourText)
  const minute = Number(minuteText)
  if (!Number.isInteger(hour) || !Number.isInteger(minute)) {
    return value
  }
  const suffix = hour >= 12 ? 'PM' : 'AM'
  const displayHour = hour % 12 || 12
  return `${displayHour}:${String(minute).padStart(2, '0')} ${suffix}`
}

export const formatAttendanceTimeRange = (
  startTime?: string | null,
  endTime?: string | null,
): string => endTime
  ? `${formatAttendanceTime(startTime)} - ${formatAttendanceTime(endTime)}`
  : formatAttendanceTime(startTime)

export const pageRangeLabel = (total: number, offset: number, visibleCount: number): string => {
  if (total <= 0 || visibleCount <= 0) {
    return '0 of 0'
  }
  const start = offset + 1
  const end = Math.min(offset + visibleCount, total)
  return `${start}-${end} of ${total}`
}
