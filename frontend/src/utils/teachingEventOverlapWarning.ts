export interface ScheduledTeachingInterval {
  id: string
  postingCode: string
  eventDate: string
  startTime: string
  endTime?: string
  durationHours?: number
}

export interface ProposedTeachingInterval {
  postingCode?: string
  eventDate: string
  startTime: string
  durationHours?: number
  excludedEventId?: string
}

const timeParts = (value: string): [number, number] | null => {
  const match = /^(\d{1,2}):(\d{2})/.exec(value)
  if (!match) {
    return null
  }
  const hours = Number(match[1])
  const minutes = Number(match[2])
  return Number.isInteger(hours)
    && hours >= 0
    && hours < 24
    && Number.isInteger(minutes)
    && minutes >= 0
    && minutes < 60
    ? [hours, minutes]
    : null
}

const startMinute = (eventDate: string, startTime: string): number | null => {
  const dateParts = /^(\d{4})-(\d{2})-(\d{2})$/.exec(eventDate)
  const parsedTime = timeParts(startTime)
  if (!dateParts || !parsedTime) {
    return null
  }
  return Math.floor(Date.UTC(
    Number(dateParts[1]),
    Number(dateParts[2]) - 1,
    Number(dateParts[3]),
    parsedTime[0],
    parsedTime[1],
  ) / 60_000)
}

const intervalEndMinute = (
  start: number,
  startTime: string,
  endTime: string | undefined,
  durationHours: number | undefined,
): number | null => {
  if (endTime) {
    const parsedStart = timeParts(startTime)
    const parsedEnd = timeParts(endTime)
    if (parsedStart && parsedEnd) {
      const startClock = parsedStart[0] * 60 + parsedStart[1]
      const endClock = parsedEnd[0] * 60 + parsedEnd[1]
      const elapsed = endClock > startClock
        ? endClock - startClock
        : endClock + 24 * 60 - startClock
      return start + elapsed
    }
  }
  if (typeof durationHours !== 'number' || !Number.isFinite(durationHours) || durationHours <= 0) {
    return null
  }
  return start + Math.round(durationHours * 60)
}

export const countStaffEnvelopeOverlaps = (
  events: ScheduledTeachingInterval[],
  proposed: ProposedTeachingInterval,
): number => {
  const proposedStart = startMinute(proposed.eventDate, proposed.startTime)
  if (proposedStart === null) {
    return 0
  }
  const proposedEnd = intervalEndMinute(
    proposedStart,
    proposed.startTime,
    undefined,
    proposed.durationHours,
  )
  if (proposedEnd === null) {
    return 0
  }

  return events.filter((event) => {
    if (event.id === proposed.excludedEventId) {
      return false
    }
    if (proposed.postingCode && event.postingCode !== proposed.postingCode) {
      return false
    }
    const existingStart = startMinute(event.eventDate, event.startTime)
    if (existingStart === null) {
      return false
    }
    const existingEnd = intervalEndMinute(
      existingStart,
      event.startTime,
      event.endTime,
      event.durationHours,
    )
    return existingEnd !== null
      && proposedStart < existingEnd
      && existingStart < proposedEnd
  }).length
}
