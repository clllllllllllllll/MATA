import { useCallback, useEffect, useMemo, useState } from 'react'
import { ApiRequestError } from '../../api/http'
import {
  createProgrammeTeachingEvent,
  deleteProgrammeTeachingEvent,
  duplicateProgrammeTeachingEvent,
  listProgrammeTeachingEvents,
  listProgrammeTeachingNameOptions,
  updateProgrammeTeachingEvent,
  type ProgrammeTeachingEvent,
  type ProgrammeTeachingNameOption,
} from '../../api/programmeTeachingEvents'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconPlus, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { useAppState } from '../../context/useAppState'
import { useAuth } from '../../context/useAuth'
import {
  buildProgrammeTeachingEventPayload,
  canMutateProgrammeTeachingEvent,
  createdByRoleLabel,
  EMPTY_PROGRAMME_TEACHING_EVENT_FORM,
  formStateFromEvent,
  postingOptionsForSource,
  type ProgrammeTeachingEventFormState,
} from './pcTeachingEventsPageLogic'
import { resolvePcProgrammeScope } from './pcUploadTtfPageLogic'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'
import {
  formatReportingPeriodOptionLabel,
  isEffectivelyActiveReportingPeriod,
  validatedReportingPeriod,
  withValidatedReportingPeriod,
} from '../../utils/reportingPeriods'
import {
  canAddTeachingFromOptions,
  resolveTeachingNameOptionsState,
} from '../../utils/teachingNameOptionsState'
import { serverComputedPoolEndTime } from '../../utils/secretaryTeachingScheduleState'
import { countStaffEnvelopeOverlaps } from '../../utils/teachingEventOverlapWarning'

type DrawerMode = 'create' | 'edit' | 'duplicate'

const todayIso = () => new Date().toISOString().slice(0, 10)

const START_TIME_OPTIONS = Array.from({ length: 24 * 4 }, (_, index) => {
  const totalMinutes = index * 15
  const hours = Math.floor(totalMinutes / 60)
  const minutes = totalMinutes % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}`
})

const formatDate = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  const parsed = new Date(value)
  if (!Number.isFinite(parsed.getTime())) {
    return value
  }
  return parsed.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

const formatCompactDate = (value?: string | null) => formatDate(value)

const formatTime = (value?: string | null) => {
  if (!value) {
    return '-'
  }
  const parts = value.split(':')
  if (parts.length < 2) {
    return value
  }
  const hours = Number(parts[0])
  const minutes = parts[1]
  if (!Number.isFinite(hours)) {
    return value
  }
  const suffix = hours >= 12 ? 'pm' : 'am'
  const hour12 = hours % 12 || 12
  return `${String(hour12).padStart(2, '0')}:${minutes} ${suffix}`
}

const formatDuration = (value?: number | null) => {
  if (value === undefined || value === null) {
    return '-'
  }
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)}h`
}

const formatStaffEventDuration = (
  event: Pick<ProgrammeTeachingEvent, 'durationHours' | 'durationVaries'>,
) => event.durationVaries
  ? `Varies by R-year (up to ${formatDuration(event.durationHours)})`
  : formatDuration(event.durationHours)

const eventErrorMessage = (error: unknown, fallback: string) =>
  error instanceof ApiRequestError
    ? formatUserFacingApiError(error, { fallbackMessage: fallback })
    : fallback

const emptyForm = (programmeCode: string): ProgrammeTeachingEventFormState => ({
  ...EMPTY_PROGRAMME_TEACHING_EVENT_FORM,
  programmeCode,
  eventDate: todayIso(),
  startTime: '08:00',
})

const selectedPeriodRange = (period?: { startDate: string; endDate: string }) =>
  period ? { dateFrom: period.startDate, dateTo: period.endDate } : {}

export const PcTeachingEventsPage = () => {
  const {
    reportingPeriodId,
    reportingPeriods,
    setReportingPeriodId,
    selectedProgrammeCode,
    setSelectedProgrammeCode,
    demoAdminId,
  } = useAppState()
  const { identity } = useAuth()

  const [events, setEvents] = useState<ProgrammeTeachingEvent[]>([])
  const [eventsLoading, setEventsLoading] = useState(true)
  const [eventsError, setEventsError] = useState<string | null>(null)
  const [nameOptions, setNameOptions] = useState<ProgrammeTeachingNameOption[]>([])
  const [nameOptionsLoading, setNameOptionsLoading] = useState(false)
  const [nameOptionsError, setNameOptionsError] = useState<string | null>(null)
  const [loadedNameOptionsContextKey, setLoadedNameOptionsContextKey] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerMode, setDrawerMode] = useState<DrawerMode>('create')
  const [sourceEvent, setSourceEvent] = useState<ProgrammeTeachingEvent | null>(null)
  const [formState, setFormState] = useState<ProgrammeTeachingEventFormState>(() => emptyForm(selectedProgrammeCode))
  const [formErrors, setFormErrors] = useState<Partial<Record<keyof ProgrammeTeachingEventFormState, string>>>({})
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())
  const [selectionMessage, setSelectionMessage] = useState<string | null>(null)
  const [selectionMessageTone, setSelectionMessageTone] = useState<'success' | 'warning'>('warning')
  const pcProgrammeScope = useMemo(
    () => (identity?.role === 'programme_pc' ? identity.programmeScope : []),
    [identity],
  )
  const pcAdminId = identity?.role === 'programme_pc' ? identity.subjectId : demoAdminId

  const programmeScope = useMemo(
    () => resolvePcProgrammeScope(pcProgrammeScope, selectedProgrammeCode),
    [pcProgrammeScope, selectedProgrammeCode],
  )
  const selectedPcProgrammeCode = programmeScope.selectedProgrammeCode
  const selectedPeriod = useMemo(() => {
    const candidate = validatedReportingPeriod(reportingPeriods, reportingPeriodId)
    return candidate && isEffectivelyActiveReportingPeriod(candidate) ? candidate : undefined
  }, [reportingPeriodId, reportingPeriods])
  const nameOptionsContextKey = selectedPcProgrammeCode && selectedPeriod
    ? `${selectedPcProgrammeCode}:${selectedPeriod.id}`
    : null
  const nameOptionsState = resolveTeachingNameOptionsState({
    hasContext: Boolean(nameOptionsContextKey),
    isLoading: nameOptionsLoading,
    isLoaded: loadedNameOptionsContextKey === nameOptionsContextKey,
    error: nameOptionsError,
    optionCount: nameOptions.length,
  })
  const canAddTeaching = canAddTeachingFromOptions(nameOptionsState)
  const addTeachingTitle = useMemo(() => {
    if (programmeScope.mode === 'none') {
      return 'No programme scope is available.'
    }
    if (nameOptionsState === 'unavailable') {
      return 'Select an active reporting period before adding teaching.'
    }
    if (nameOptionsState === 'loading') {
      return 'Teaching-name options are loading.'
    }
    if (nameOptionsState === 'error') {
      return 'Teaching-name options could not be loaded.'
    }
    if (nameOptionsState === 'empty') {
      return 'No teaching-name options are available for this programme and reporting period.'
    }
    return 'Add a programme teaching event.'
  }, [nameOptionsState, programmeScope.mode])
  const dateRange = useMemo(() => selectedPeriodRange(selectedPeriod), [selectedPeriod])
  const optionsBySourceKey = useMemo(() => {
    const bySourceKey = new Map<string, ProgrammeTeachingNameOption>()
    nameOptions.forEach((option) => {
      bySourceKey.set(option.sourceKey, option)
    })
    return bySourceKey
  }, [nameOptions])
  const retainedInactiveGlobalOption = useMemo<ProgrammeTeachingNameOption | undefined>(() => {
    if (drawerMode !== 'edit' || !sourceEvent?.globalSessionTypeId) {
      return undefined
    }
    const sourceKey = `global-session-type:${sourceEvent.globalSessionTypeId}`
    if (optionsBySourceKey.has(sourceKey)) {
      return undefined
    }
    const activeGlobalPostingCodes = nameOptions.find((option) => option.isGlobal)?.postingCodes
    return {
      sourceKey,
      keyword: sourceEvent.teachingName,
      globalSessionTypeId: sourceEvent.globalSessionTypeId,
      sessionTypeId: sourceEvent.sessionTypeId,
      sessionType: sourceEvent.sessionTypeName,
      durationHours: sourceEvent.durationHours,
      isGlobal: true,
      postingCodes: activeGlobalPostingCodes?.length ? activeGlobalPostingCodes : [sourceEvent.postingCode],
    }
  }, [drawerMode, nameOptions, optionsBySourceKey, sourceEvent])
  const drawerSourceOptions = useMemo(
    () => retainedInactiveGlobalOption ? [...nameOptions, retainedInactiveGlobalOption] : nameOptions,
    [nameOptions, retainedInactiveGlobalOption],
  )
  const selectedSourceOption =
    optionsBySourceKey.get(formState.sourceKey)
    ?? (retainedInactiveGlobalOption?.sourceKey === formState.sourceKey
      ? retainedInactiveGlobalOption
      : undefined)
  const selectedOptionPostingCodes = useMemo(
    () => postingOptionsForSource(drawerSourceOptions, formState.sourceKey),
    [drawerSourceOptions, formState.sourceKey],
  )
  const selectedPostingDuration = selectedSourceOption?.teachingNameId
    ? selectedSourceOption.postingDurations?.find(
        (entry) => entry.postingCode === formState.postingCode,
      )
    : undefined
  const selectedMappedPoolEndTime = selectedPostingDuration?.isMapped
    && !selectedPostingDuration.durationVaries
    ? serverComputedPoolEndTime(
        formState.startTime,
        selectedPostingDuration.durationHours,
      )
    : null
  const selectedPostingRYearDurations = selectedPostingDuration?.rYearDurations ?? []
  const selectedPostingHasNoMappedDurations = Boolean(
    selectedPostingDuration
    && (
      selectedPostingRYearDurations.length > 0
        ? selectedPostingRYearDurations.every((timing) => !timing.isMapped)
        : !selectedPostingDuration.isMapped
    ),
  )
  const selectedPostingNeedsRYearBreakdown = Boolean(
    selectedPostingDuration
    && !selectedPostingHasNoMappedDurations
    && (selectedPostingDuration.durationVaries || selectedPostingDuration.hasPendingMappings),
  )
  const overlapWarningCount = countStaffEnvelopeOverlaps(
    events,
    {
      postingCode: formState.postingCode,
      eventDate: formState.eventDate,
      startTime: formState.startTime,
      durationHours: selectedPostingDuration?.durationHours ?? selectedSourceOption?.durationHours,
      excludedEventId: drawerMode === 'edit' ? sourceEvent?.id : undefined,
    },
  )
  const isSelectedSourceOption = Boolean(selectedSourceOption)
  const canSubmitTeaching = canAddTeaching || Boolean(retainedInactiveGlobalOption)
  const selectedRows = useMemo(() => events.filter((event) => selectedIds.has(event.id)), [events, selectedIds])
  const selectedCount = selectedRows.length
  const selectedWithAttendanceCount = selectedRows.filter((event) => event.hasAttendance).length
  const allSelectedHaveAttendance = selectedCount > 0 && selectedWithAttendanceCount === selectedCount
  const anySelectedHaveAttendance = selectedWithAttendanceCount > 0
  const deletableRows = selectedRows.filter((event) => !event.hasAttendance)
  const canEditSelected = selectedCount === 1 && !selectedRows[0]?.hasAttendance
  const canDuplicateSelected = selectedCount === 1
  const canDeleteSelected = selectedCount > 0 && !allSelectedHaveAttendance
  const showEditButton = canEditSelected
  const showDeleteButton = canDeleteSelected
  const showDuplicateButton = canDuplicateSelected
  const singleSelectedEvent = useMemo(() => {
    if (selectedCount !== 1) {
      return null
    }
    return selectedRows[0] ?? null
  }, [selectedCount, selectedRows])
  const selectedActionMessage = useMemo(() => {
    if (selectedCount === 0) {
      return null
    }
    if (selectedCount === 1) {
      if (singleSelectedEvent?.hasAttendance) {
        return 'Editing and deleting are disabled because attendance has been submitted for this event.'
      }
      return null
    }
    if (allSelectedHaveAttendance) {
      return 'Editing and deleting are disabled because attendance has been submitted for the selected events.'
    }
    if (anySelectedHaveAttendance) {
      return 'Some selected events cannot be edited or deleted because attendance has been submitted.'
    }
    return null
  }, [allSelectedHaveAttendance, anySelectedHaveAttendance, selectedCount, singleSelectedEvent])
  const showSelectionActionMessage = selectedActionMessage !== null && !selectionMessage

  const loadEvents = useCallback(async () => {
    if (!selectedPcProgrammeCode || !selectedPeriod) {
      setEvents([])
      setEventsLoading(false)
      return
    }
    setEventsLoading(true)
    setEventsError(null)
    try {
      const rows = await withValidatedReportingPeriod(
        reportingPeriods,
        reportingPeriodId,
        (period) => listProgrammeTeachingEvents({
          adminId: pcAdminId,
          adminProgrammes: pcProgrammeScope,
          programmeCode: selectedPcProgrammeCode,
          reportingPeriodId: period.id,
          ...dateRange,
        }),
      )
      if (!rows) {
        setEvents([])
        return
      }
      setEvents(rows)
      setSelectedIds(new Set())
      setSelectionMessage(null)
    } catch (error) {
      setEventsError(eventErrorMessage(error, 'Unable to load programme teaching events.'))
      setEvents([])
    } finally {
      setEventsLoading(false)
    }
  }, [dateRange, pcAdminId, pcProgrammeScope, reportingPeriodId, reportingPeriods, selectedPcProgrammeCode, selectedPeriod])

  useEffect(() => {
    if (selectedPcProgrammeCode && selectedProgrammeCode !== selectedPcProgrammeCode) {
      setSelectedProgrammeCode(selectedPcProgrammeCode)
    }
  }, [selectedPcProgrammeCode, selectedProgrammeCode, setSelectedProgrammeCode])

  useEffect(() => {
    let active = true
    ;(async () => {
      if (!selectedPcProgrammeCode || !selectedPeriod) {
        if (active) {
          setEvents([])
          setEventsLoading(false)
        }
        return
      }
      if (active) {
        setEventsLoading(true)
        setEventsError(null)
      }
      try {
        const rows = await withValidatedReportingPeriod(
          reportingPeriods,
          reportingPeriodId,
          (period) => listProgrammeTeachingEvents({
            adminId: pcAdminId,
            adminProgrammes: pcProgrammeScope,
            programmeCode: selectedPcProgrammeCode,
            reportingPeriodId: period.id,
            ...dateRange,
          }),
        )
        if (!rows) {
          return
        }
        if (active) {
          setEvents(rows)
          setSelectedIds(new Set())
          setSelectionMessage(null)
        }
      } catch (error) {
        if (active) {
          setEventsError(eventErrorMessage(error, 'Unable to load programme teaching events.'))
          setEvents([])
        }
      } finally {
        if (active) {
          setEventsLoading(false)
        }
      }
    })()

    return () => {
      active = false
    }
  }, [dateRange, pcAdminId, pcProgrammeScope, reportingPeriodId, reportingPeriods, selectedPcProgrammeCode, selectedPeriod])

  useEffect(() => {
    let active = true
    ;(async () => {
      if (!selectedPcProgrammeCode || !selectedPeriod) {
        if (active) {
          setNameOptions([])
          setNameOptionsError(null)
          setNameOptionsLoading(false)
          setLoadedNameOptionsContextKey(null)
        }
        return
      }
      if (active) {
        setNameOptions([])
        setNameOptionsLoading(true)
        setNameOptionsError(null)
        setLoadedNameOptionsContextKey(null)
      }
      try {
        const options = await withValidatedReportingPeriod(
          reportingPeriods,
          reportingPeriodId,
          (period) => listProgrammeTeachingNameOptions({
            adminId: pcAdminId,
            adminProgrammes: pcProgrammeScope,
            programmeCode: selectedPcProgrammeCode,
            reportingPeriodId: period.id,
          }),
        )
        if (!options) {
          return
        }
        if (active) {
          setNameOptions(options)
          setLoadedNameOptionsContextKey(nameOptionsContextKey)
        }
      } catch (error) {
        if (active) {
          setNameOptionsError(eventErrorMessage(error, 'Unable to load teaching name options.'))
          setNameOptions([])
          setLoadedNameOptionsContextKey(nameOptionsContextKey)
        }
      } finally {
        if (active) {
          setNameOptionsLoading(false)
        }
      }
    })()

    return () => {
      active = false
    }
  }, [
    nameOptionsContextKey,
    pcAdminId,
    pcProgrammeScope,
    reportingPeriodId,
    reportingPeriods,
    selectedPcProgrammeCode,
    selectedPeriod,
  ])

  const toggleSelected = (id: string) => {
    setSelectedIds((previous) => {
      const next = new Set(previous)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
    setSelectionMessage(null)
    setEventsError(null)
  }

  const clearSelection = () => {
    setSelectedIds(new Set())
    setSelectionMessage(null)
    setEventsError(null)
  }

  const handleProgrammeChange = (programmeCode: string) => {
    setSelectedProgrammeCode(programmeCode)
    setSelectedIds(new Set())
    setSelectionMessage(null)
    setFormState((previous) => ({
      ...previous,
      programmeCode,
      sourceKey: '',
      postingCode: '',
    }))
  }

  const openCreateDrawer = () => {
    if (!canAddTeaching) {
      return
    }
    setDrawerMode('create')
    setSourceEvent(null)
    setFormState(emptyForm(selectedPcProgrammeCode))
    setFormErrors({})
    setSubmitError(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (event: ProgrammeTeachingEvent) => {
    if (!canMutateProgrammeTeachingEvent(event)) {
      setEventsError('Editing and deleting are disabled because attendance has been submitted for this event.')
      return
    }
    setDrawerMode('edit')
    setSourceEvent(event)
    setFormState(formStateFromEvent(event, selectedPcProgrammeCode))
    setFormErrors({})
    setSubmitError(null)
    setDrawerOpen(true)
  }

  const openSelectedEditDrawer = () => {
    if (!singleSelectedEvent) {
      return
    }
    openEditDrawer(singleSelectedEvent)
  }

  const openDuplicateDrawer = (event: ProgrammeTeachingEvent) => {
    setDrawerMode('duplicate')
    setSourceEvent(event)
    setFormState({
      ...formStateFromEvent(event, selectedPcProgrammeCode),
      programmeCode: selectedPcProgrammeCode,
      eventDate: todayIso(),
    })
    setFormErrors({})
    setSubmitError(null)
    setDrawerOpen(true)
  }

  const openSelectedDuplicateDrawer = () => {
    if (!singleSelectedEvent) {
      return
    }
    openDuplicateDrawer(singleSelectedEvent)
  }

  const closeDrawer = () => {
    setDrawerOpen(false)
    setSourceEvent(null)
    setSubmitting(false)
  }

  const handleDeleteSelected = async () => {
    if (allSelectedHaveAttendance) {
      setSelectionMessageTone('warning')
      setSelectionMessage(`${selectedCount} teaching event(s) cannot be deleted because attendance exists.`)
      return
    }

    const idsToDelete = deletableRows.map((event) => event.id)
    const attendanceProtectedIds = selectedRows.filter((event) => event.hasAttendance).map((event) => event.id)
    const attendanceProtectedCount = attendanceProtectedIds.length

    if (idsToDelete.length === 0) {
      setSelectionMessageTone('warning')
      setSelectionMessage(`${attendanceProtectedCount} teaching event(s) cannot be deleted because attendance exists.`)
      return
    }

    setSubmitting(true)
    setEventsError(null)
    setSelectionMessage(null)
    const deleteAttempts = await Promise.allSettled(
      deletableRows.map((event) =>
        deleteProgrammeTeachingEvent({
          adminId: pcAdminId,
          adminProgrammes: pcProgrammeScope,
          eventId: event.id,
          programmeCode: event.createdForProgrammeCode || selectedPcProgrammeCode,
        }),
      ),
    )
    const deletedIds = idsToDelete.filter((_, index) => deleteAttempts[index]?.status === 'fulfilled')
    const failedIds = idsToDelete.filter((_, index) => deleteAttempts[index]?.status === 'rejected')

    try {
      if (deletedIds.length > 0) {
        await loadEvents()
      }
      setSelectedIds(new Set([...attendanceProtectedIds, ...failedIds]))
      if (failedIds.length === 0) {
        setSelectionMessageTone('success')
        setSelectionMessage(
          attendanceProtectedCount > 0
            ? `Deleted ${deletedIds.length} teaching event(s). ${attendanceProtectedCount} could not be deleted because attendance exists.`
            : `Deleted ${deletedIds.length} teaching event(s).`,
        )
      } else {
        setSelectionMessageTone('warning')
        setSelectionMessage(
          `Deleted ${deletedIds.length} teaching event(s). ${failedIds.length} could not be deleted right now.`,
        )
      }
    } catch (error) {
      setEventsError(eventErrorMessage(error, 'Teaching event could not be deleted.'))
    } finally {
      setSubmitting(false)
    }
  }

  const validateForm = () => {
    const errors: Partial<Record<keyof ProgrammeTeachingEventFormState, string>> = {}
    const payload = buildProgrammeTeachingEventPayload(formState, selectedSourceOption)
    if (!payload.programmeCode) {
      errors.programmeCode = 'Programme is required.'
    }
    if (!payload.postingCode) {
      errors.postingCode = 'Posting code is required.'
    }
    if (!formState.sourceKey) {
      errors.sourceKey = 'Teaching name is required.'
    } else if (!selectedSourceOption) {
      errors.sourceKey = 'Select a teaching name from the programme teaching-name pool.'
    }
    if (!payload.eventDate) {
      errors.eventDate = 'Event date is required.'
    } else if (
      selectedPeriod &&
      (payload.eventDate < selectedPeriod.startDate || payload.eventDate > selectedPeriod.endDate)
    ) {
      errors.eventDate = 'Event date must be within the selected reporting period.'
    }
    if (!payload.startTime) {
      errors.startTime = 'Start time is required.'
    }
    if (
      selectedOptionPostingCodes.length > 0 &&
      payload.postingCode &&
      !selectedOptionPostingCodes.includes(payload.postingCode)
    ) {
      errors.postingCode = 'Posting code must match the selected teaching name option.'
    }
    setFormErrors(errors)
    return Object.keys(errors).length === 0
  }

  const saveEvent = async () => {
    if (!validateForm()) {
      return
    }
    if (drawerMode === 'edit' && (!sourceEvent || !canMutateProgrammeTeachingEvent(sourceEvent))) {
      setSubmitError('This teaching event cannot be edited because attendance exists.')
      return
    }

    setSubmitting(true)
    setSubmitError(null)
    const payload = buildProgrammeTeachingEventPayload(formState, selectedSourceOption)
    try {
      if (drawerMode === 'edit' && sourceEvent) {
        await updateProgrammeTeachingEvent({
          adminId: pcAdminId,
          adminProgrammes: pcProgrammeScope,
          eventId: sourceEvent.id,
          payload,
        })
      } else if (drawerMode === 'duplicate' && sourceEvent) {
        await duplicateProgrammeTeachingEvent({
          adminId: pcAdminId,
          adminProgrammes: pcProgrammeScope,
          eventId: sourceEvent.id,
          payload,
        })
      } else {
        await createProgrammeTeachingEvent({
          adminId: pcAdminId,
          adminProgrammes: pcProgrammeScope,
          payload,
        })
      }
      closeDrawer()
      await loadEvents()
    } catch (error) {
      setSubmitError(eventErrorMessage(error, 'Teaching event could not be saved.'))
    } finally {
      setSubmitting(false)
    }
  }

  const updateField = <K extends keyof ProgrammeTeachingEventFormState>(
    field: K,
    value: ProgrammeTeachingEventFormState[K],
  ) => {
    setFormState((previous) => ({
      ...previous,
      [field]: value,
      ...(field === 'sourceKey' ? { postingCode: '' } : {}),
    }))
  }

  const eventsCountLabel = `${events.length} event${events.length === 1 ? '' : 's'}`

  return (
    <div className="page pc-teaching-events-page">
      <PageHero
        title="Teaching Events"
        subtitle="PC - scheduled teaching events"
        actions={
          <div className="pc-teaching-events-actions">
            <button type="button" className="button button-secondary" onClick={() => void loadEvents()}>
              <IconRefresh size={14} />
              Refresh
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={openCreateDrawer}
              disabled={programmeScope.mode === 'none' || !canAddTeaching}
              title={addTeachingTitle}
            >
              <IconPlus size={14} />
              Add Teaching
            </button>
          </div>
        }
      />

      <section className="card control-panel pc-teaching-events-controls">
        <div className="pc-teaching-events-control-grid">
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
                onChange={(event) => handleProgrammeChange(event.target.value)}
              >
                {programmeScope.programmeOptions.map((programme) => (
                  <option key={programme.code} value={programme.code}>
                    {programme.label}
                  </option>
                ))}
              </select>
            ) : null}
            {programmeScope.mode === 'none' ? (
              <span className="upload-validation-text">No programme scope is available.</span>
            ) : null}
          </label>
          <label>
            Reporting period
            <select
              value={selectedPeriod?.id ?? ''}
              onChange={(event) => setReportingPeriodId(event.target.value)}
            >
              <option value="">Select an active reporting period</option>
              {reportingPeriods.map((period) => {
                const active = isEffectivelyActiveReportingPeriod(period)
                return (
                  <option key={period.id} value={period.id} disabled={!active}>
                    {formatReportingPeriodOptionLabel(period)}{active ? '' : ' — inactive'}
                  </option>
                )
              })}
            </select>
          </label>
        </div>
        {nameOptionsState === 'loading' ? (
          <div className="inline-callout pc-teaching-events-callout">
            <span>Loading teaching-name options...</span>
          </div>
        ) : null}
        {nameOptionsState === 'unavailable' && selectedPcProgrammeCode ? (
          <div className="inline-callout callout-warning pc-teaching-events-callout">
            <span>Select an active reporting period to load teaching-name options.</span>
          </div>
        ) : null}
        {nameOptionsState === 'error' && nameOptionsError ? (
          <div className="inline-callout callout-warning pc-teaching-events-callout">
            <span>{nameOptionsError}</span>
          </div>
        ) : null}
        {nameOptionsState === 'empty' ? (
          <div className="inline-callout callout-warning pc-teaching-events-callout">
            <span>No teaching-name options are available for this programme and reporting period.</span>
          </div>
        ) : null}
      </section>

      <section className="card pc-teaching-events-table-card">
        <div className="section-header pc-teaching-events-heading">
          <h2>Teaching schedule</h2>
          {selectedCount > 0 ? (
            <span className="inline-muted secretary-selection-count">{selectedCount} selected</span>
          ) : (
            <span className="inline-muted secretary-selection-helper">{eventsCountLabel}</span>
          )}
          <p className="secretary-edit-preface pc-teaching-events-edit-preface">
            Only teachings with no submitted attendance can be edited.
          </p>
          {selectedCount > 0 ? (
            <div className="secretary-selection-toolbar">
              {showEditButton ? (
                <button
                  type="button"
                  className="button button-ghost secretary-mobile-action-button secretary-toolbar-edit-button"
                  onClick={openSelectedEditDrawer}
                  title="Edit selected teaching event."
                >
                  Edit
                </button>
              ) : null}
              {showDuplicateButton ? (
                <button
                  type="button"
                  className="button button-secondary secretary-mobile-action-button"
                  onClick={openSelectedDuplicateDrawer}
                  title={
                    selectedCount === 1
                      ? 'Create a duplicate of the selected teaching event.'
                      : 'Select exactly one row to duplicate.'
                  }
                >
                  Duplicate
                </button>
              ) : null}
              {showDeleteButton ? (
                <button
                  type="button"
                  className="button button-ghost danger secretary-mobile-action-button"
                  onClick={() => void handleDeleteSelected()}
                  title="Delete selected teaching event(s)."
                >
                  Delete
                </button>
              ) : null}
              <button
                type="button"
                className="button button-ghost secretary-mobile-action-button"
                onClick={(event) => {
                  event.preventDefault()
                  event.stopPropagation()
                  clearSelection()
                }}
              >
                Clear
              </button>
            </div>
          ) : null}
        </div>
        {showSelectionActionMessage ? (
          <div className="inline-callout callout-warning secretary-inline-callout secretary-selection-warning">
            <span>{selectedActionMessage}</span>
          </div>
        ) : null}
        {selectionMessage ? (
          <div
            className={`inline-callout secretary-inline-callout ${
              selectionMessageTone === 'success' ? 'callout-success' : 'callout-warning'
            }`}
          >
            <span>{selectionMessage}</span>
          </div>
        ) : null}
        {eventsError ? (
          <div className="inline-callout callout-warning secretary-inline-callout">
            <span>{eventsError}</span>
          </div>
        ) : null}
        <div className="table-wrap pc-teaching-events-table-wrap">
          <div className={`table-scroll ${eventsLoading ? 'is-loading' : ''}`}>
            <table className="table pc-teaching-events-table">
              <thead>
                <tr>
                  <th className="col-check" />
                  <th>Session Type</th>
                  <th>Name of Teaching</th>
                  <th>Posting</th>
                  <th>Date</th>
                  <th>Start Time</th>
                  <th>Duration</th>
                  <th>CME Pts</th>
                  <th>SMC Event</th>
                  <th>Created By</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {eventsLoading ? (
                  <tr>
                    <td colSpan={11}>Loading teaching events...</td>
                  </tr>
                ) : events.length === 0 ? (
                  <tr>
                    <td colSpan={11}>No teaching events found.</td>
                  </tr>
                ) : (
                  events.map((event) => {
                    const selected = selectedIds.has(event.id)
                    const teachingType = event.sessionTypeName ?? '-'
                    return (
                      <tr
                        key={event.id}
                        className={`table-clickable-row ${selected ? 'secretary-row-selected' : ''}`}
                        onClick={() => toggleSelected(event.id)}
                      >
                        <td>
                          <input
                            type="checkbox"
                            checked={selected}
                            onChange={() => toggleSelected(event.id)}
                            onClick={(clickEvent) => clickEvent.stopPropagation()}
                            aria-label={`Select ${event.teachingName}`}
                          />
                        </td>
                        <td className="pc-teaching-events-session-cell">
                          <span className="secretary-type-pill">{teachingType}</span>
                        </td>
                        <td className="secretary-teaching-name pc-teaching-events-name-cell">{event.teachingName}</td>
                        <td className="pc-teaching-events-posting-cell pc-teaching-events-nowrap">{event.postingCode}</td>
                        <td className="pc-teaching-events-date-cell pc-teaching-events-nowrap mono">
                          {formatDate(event.eventDate)}
                        </td>
                        <td className="pc-teaching-events-time-cell pc-teaching-events-nowrap mono">
                          {formatTime(event.startTime)}
                        </td>
                        <td className="pc-teaching-events-duration-cell pc-teaching-events-nowrap">
                          {formatStaffEventDuration(event)}
                        </td>
                        <td className="pc-teaching-events-cme-cell pc-teaching-events-nowrap">
                          <span
                            className={`status-badge ${
                              event.cmePointsAwarded ? 'status-badge-success' : 'status-badge-neutral'
                            }`}
                          >
                            {event.cmePointsAwarded ? 'Yes' : 'No'}
                          </span>
                        </td>
                        <td className="pc-teaching-events-smc-cell pc-teaching-events-nowrap mono">
                          {event.smcEventCode ?? '-'}
                        </td>
                        <td className="pc-teaching-events-created-by-cell pc-teaching-events-nowrap">
                          {createdByRoleLabel(event.createdByRole)}
                        </td>
                        <td className="pc-teaching-events-created-cell pc-teaching-events-nowrap">
                          {formatDate(event.createdAt)}
                        </td>
                      </tr>
                    )
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
        <div className="secretary-event-card-list pc-event-card-list" aria-label="Teaching schedule cards">
          {eventsLoading ? (
            <div className="mobile-record-card secretary-event-empty-card">Loading teaching events...</div>
          ) : events.length === 0 ? (
            <div className="mobile-record-card secretary-event-empty-card">No teaching events found.</div>
          ) : (
            events.map((event) => {
              const selected = selectedIds.has(event.id)
              const teachingType = event.sessionTypeName ?? '-'
              const attendanceTotal = event.attendanceCount + event.externalAttendanceCount

              return (
                <article
                  key={event.id}
                  className={`mobile-record-card secretary-event-card ${selected ? 'is-selected' : ''} ${
                    event.hasAttendance ? 'has-attendance' : ''
                  }`}
                  aria-label={event.teachingName}
                >
                  <span className="secretary-event-card-header">
                    <span className="secretary-event-card-title safe-wrap">{event.teachingName}</span>
                    <span className="secretary-event-card-badges">
                      <span
                        className={`status-badge ${
                          event.cmePointsAwarded ? 'status-badge-success' : 'status-badge-neutral'
                        }`}
                      >
                        {event.cmePointsAwarded ? 'CME Yes' : 'CME No'}
                      </span>
                    </span>
                  </span>
                  <span className="secretary-event-card-meta">
                    <span className="secretary-event-card-line mono">
                      {formatCompactDate(event.eventDate)} · {formatTime(event.startTime)} ·{' '}
                      {formatStaffEventDuration(event)}
                    </span>
                    {teachingType !== '-' ? (
                      <span className="secretary-event-card-line safe-wrap">{teachingType}</span>
                    ) : null}
                    <span className="secretary-event-card-line">Posting {event.postingCode}</span>
                    <span className="secretary-event-card-line">
                      {createdByRoleLabel(event.createdByRole)}
                      {event.hasAttendance ? ` · Attendance submitted (${attendanceTotal})` : ''}
                      {event.smcEventCode ? ` · SMC ${event.smcEventCode}` : ''}
                    </span>
                  </span>
                  <span className={`secretary-card-action-row ${event.hasAttendance ? 'is-single' : ''}`}>
                    <button
                      type="button"
                      className="secretary-mobile-action-button secretary-card-select-indicator"
                      onClick={() => toggleSelected(event.id)}
                      aria-pressed={selected}
                      aria-label={`${selected ? 'Deselect' : 'Select'} ${event.teachingName}`}
                    >
                      {selected ? 'Selected' : 'Select'}
                    </button>
                    {!event.hasAttendance ? (
                      <button
                        type="button"
                        className="button button-secondary secretary-mobile-action-button secretary-card-edit-button"
                        onClick={(clickEvent) => {
                          clickEvent.stopPropagation()
                          openEditDrawer(event)
                        }}
                      >
                        Edit
                      </button>
                    ) : null}
                  </span>
                </article>
              )
            })
          )}
        </div>
      </section>

      <DetailDrawer
        title={drawerMode === 'duplicate' ? 'Duplicate Teaching' : drawerMode === 'edit' ? 'Edit Teaching' : 'Add Teaching'}
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="button button-ghost" onClick={closeDrawer}>
              Cancel
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={() => void saveEvent()}
              disabled={
                submitting
                || !canSubmitTeaching
                || (drawerMode === 'edit' && !canMutateProgrammeTeachingEvent(sourceEvent))
              }
            >
              {submitting
                ? 'Saving...'
                : drawerMode === 'duplicate'
                  ? 'Create duplicate'
                  : drawerMode === 'edit'
                    ? 'Save changes'
                    : 'Create teaching'}
            </button>
          </>
        }
      >
        <div className="secretary-form-grid pc-teaching-events-form-grid">
          <label className="pc-drawer-programme-field">
            Programme
            {programmeScope.mode === 'locked' ? (
              <input
                type="text"
                className="pc-programme-readonly-field"
                value={programmeScope.selectedProgrammeLabel || formState.programmeCode}
                readOnly
              />
            ) : null}
            {programmeScope.mode === 'select' ? (
              <select
                value={formState.programmeCode || selectedPcProgrammeCode}
                onChange={(event) => handleProgrammeChange(event.target.value)}
              >
                {programmeScope.programmeOptions.map((programme) => (
                  <option key={programme.code} value={programme.code}>
                    {programme.label}
                  </option>
                ))}
              </select>
            ) : null}
            {programmeScope.mode === 'none' ? (
              <span className="upload-validation-text">No programme scope is available.</span>
            ) : null}
            {formErrors.programmeCode ? (
              <small className="upload-validation-text">{formErrors.programmeCode}</small>
            ) : null}
          </label>

          <label>
            Teaching name
            <select
              value={formState.sourceKey}
              onChange={(event) => updateField('sourceKey', event.target.value)}
              disabled={!canSubmitTeaching}
            >
              <option value="">Select teaching name</option>
              {drawerSourceOptions.map((option) => (
                <option key={option.sourceKey} value={option.sourceKey}>
                  {option.keyword}
                  {option.sourceKey === retainedInactiveGlobalOption?.sourceKey
                    ? ' (current inactive global source)'
                    : ''}
                </option>
              ))}
            </select>
            {formErrors.sourceKey ? (
              <small className="upload-validation-text">{formErrors.sourceKey}</small>
            ) : null}
            {nameOptionsError ? <small className="upload-validation-text">{nameOptionsError}</small> : null}
          </label>

          <label>
            Posting
            <select
              className="pc-drawer-posting-select"
              value={formState.postingCode}
              onChange={(event) => updateField('postingCode', event.target.value)}
              disabled={!formState.sourceKey || selectedOptionPostingCodes.length === 0}
            >
              <option value="">
                {!formState.sourceKey
                  ? 'Select teaching name first'
                  : selectedOptionPostingCodes.length === 0
                    ? 'No postings available'
                    : 'Select posting'}
              </option>
              {selectedOptionPostingCodes.map((postingCode) => (
                <option key={postingCode} value={postingCode}>
                  {postingCode}
                </option>
              ))}
            </select>
            {formErrors.postingCode ? (
              <small className="upload-validation-text">{formErrors.postingCode}</small>
            ) : null}
            {formState.sourceKey && isSelectedSourceOption && selectedOptionPostingCodes.length === 0 ? (
              <small className="upload-validation-text">
                No postings are available for the selected teaching name.
              </small>
            ) : null}
          </label>

          {selectedSourceOption?.teachingNameId
            && formState.postingCode
            && selectedPostingDuration
            && selectedPostingHasNoMappedDurations ? (
              <div className="inline-callout callout-neutral" role="status">
                This Teaching Name has not been mapped by the Programme PC. This event will use a temporary one-hour duration. Once mapped, the system will automatically update its duration and end time.
              </div>
            ) : selectedPostingNeedsRYearBreakdown ? (
              <div className="secretary-toggle-block" aria-live="polite">
                <span className="secretary-toggle-label">
                  {selectedPostingDuration?.durationVaries ? 'Duration varies by R-year' : 'Duration by R-year'}
                </span>
                {selectedPostingRYearDurations.map((timing) => (
                  <strong key={timing.rYear}>
                    {timing.rYear}: {formatDuration(timing.durationHours)}
                    {timing.isMapped ? '' : ' (temporary until mapped)'}
                  </strong>
                ))}
                <small>
                  Staff scheduling uses the longest duration. Each native resident receives the duration mapped to their event-date R-year.
                </small>
              </div>
            ) : selectedPostingDuration?.isMapped ? (
              <div className="secretary-toggle-block" aria-live="polite">
                <span className="secretary-toggle-label">Duration</span>
                <strong>{formatDuration(selectedPostingDuration.durationHours)} (TTF mapping)</strong>
                <small>End time is calculated by the server.</small>
              </div>
            ) : selectedSourceOption?.globalSessionTypeId ? (
              <div className="secretary-toggle-block" aria-live="polite">
                <span className="secretary-toggle-label">Duration</span>
                <strong>{formatDuration(selectedSourceOption.durationHours)} (global source)</strong>
                <small>End time is calculated by the server.</small>
              </div>
            ) : null}

          <div className="secretary-form-row">
            <label>
              Event date
              <input
                type="date"
                value={formState.eventDate}
                min={selectedPeriod?.startDate}
                max={selectedPeriod?.endDate}
                onChange={(event) => updateField('eventDate', event.target.value)}
              />
              {formErrors.eventDate ? (
                <small className="upload-validation-text">{formErrors.eventDate}</small>
              ) : null}
            </label>

            <label>
              Start time
              <select value={formState.startTime} onChange={(event) => updateField('startTime', event.target.value)}>
                <option value="">Select start time</option>
                {START_TIME_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
              {formErrors.startTime ? (
                <small className="upload-validation-text">{formErrors.startTime}</small>
              ) : null}
            </label>
          </div>

          {selectedPostingNeedsRYearBreakdown ? (
            <div className="secretary-toggle-block" aria-live="polite">
              <span className="secretary-toggle-label">End time by R-year</span>
              {selectedPostingRYearDurations.map((timing) => (
                <strong key={timing.rYear}>
                  {timing.rYear}: {serverComputedPoolEndTime(formState.startTime, timing.durationHours) ?? 'Select a valid start time'}
                </strong>
              ))}
              <small>
                Staff schedule envelope ends at {
                  serverComputedPoolEndTime(
                    formState.startTime,
                    selectedPostingDuration?.durationHours,
                  ) ?? 'a valid calculated time'
                }.
              </small>
            </div>
          ) : selectedPostingDuration?.isMapped ? (
            <div className="secretary-toggle-block" aria-live="polite">
              <span className="secretary-toggle-label">End time</span>
              <strong>{selectedMappedPoolEndTime ?? 'Select a valid start time'}</strong>
              <small>Server-computed from the posting-specific TTF mapping.</small>
            </div>
          ) : null}

          {overlapWarningCount > 0 ? (
            <div className="inline-callout callout-warning" role="status">
              This time overlaps {overlapWarningCount} existing scheduled event{overlapWarningCount === 1 ? '' : 's'} within the staff scheduling envelope. Overlapping sessions are allowed. Residents will see eligible alternatives and should submit only the session they attended.
            </div>
          ) : null}

          <div className="secretary-toggle-block">
            <span className="secretary-toggle-label">CME points awarded</span>
            <div className="secretary-yes-no">
              <button
                type="button"
                className={!formState.cmePointsAwarded ? 'is-active' : ''}
                onClick={() => {
                  updateField('cmePointsAwarded', false)
                  updateField('smcEventCode', '')
                }}
              >
                No
              </button>
              <button
                type="button"
                className={formState.cmePointsAwarded ? 'is-active' : ''}
                onClick={() => updateField('cmePointsAwarded', true)}
              >
                Yes
              </button>
            </div>
          </div>

          {formState.cmePointsAwarded ? (
            <label>
              SMC event code (optional)
              <input
                type="text"
                value={formState.smcEventCode}
                onChange={(event) => updateField('smcEventCode', event.target.value)}
                placeholder="SMC-XXXX-001"
              />
              <small>Shown for CME-awarded sessions. Leave empty if not applicable.</small>
            </label>
          ) : null}

          {submitError ? (
            <div className="inline-callout callout-error">
              <span>{submitError}</span>
            </div>
          ) : null}
        </div>
      </DetailDrawer>
    </div>
  )
}
