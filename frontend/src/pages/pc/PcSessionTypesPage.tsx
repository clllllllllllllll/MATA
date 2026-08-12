import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ApiRequestError } from '../../api/http'
import {
  applyProgrammePcTeachingNameMapping,
  applyProgrammePcTeachingNameMappingBulk,
  createProgrammePcTeachingName,
  deactivateProgrammePcTeachingName,
  deleteProgrammePcTeachingName,
  getProgrammePcTeachingNameMappingImpact,
  isTeachingNameMappingRevisionConflict,
  listProgrammePcTeachingNameMappings,
  listProgrammePcTeachingNames,
  mappingImpactFromConflict,
  reactivateProgrammePcTeachingName,
  renameProgrammePcTeachingName,
  type ProgrammePcTeachingName,
  type ProgrammePcTeachingNameMapping,
  type TeachingNameMappingImpact,
  type TeachingNameMappingState,
} from '../../api/pcTeachingNameMappings'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconPlus, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { useAppState } from '../../context/useAppState'
import { useAuth } from '../../context/useAuth'
import { resolvePcProgrammeScope } from './pcUploadTtfPageLogic'
import {
  MAX_BULK_MAPPING_ITEMS,
  prepareBulkMappingChanges,
  targetOptionLabel,
  targetOptionsForMapping,
  type PreparedBulkMappingItem,
} from './pcSessionTypesPageLogic'
import {
  createPcSessionTypesInteractionCoordinator,
  type PcSessionTypesOverlay,
  type PcSessionTypesPendingAction,
  type PcSessionTypesInteractionSnapshot,
} from './pcSessionTypesInteractionCoordinator'
import {
  formatReportingPeriodOptionLabel,
  isEffectivelyActiveReportingPeriod,
  validatedReportingPeriod,
} from '../../utils/reportingPeriods'
import { createScopedRequestFence } from '../../utils/scopedRequestFence'
import { resolveTeachingNameLifecycleError } from '../../utils/secretaryTeachingNameState'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'

type LifecycleFilter = 'active' | 'inactive' | 'all'
type MappingFilter = TeachingNameMappingState | 'all'
type FeedbackTone = 'success' | 'warning'
type NameDrawerMode = 'create' | 'edit'

interface SingleConfirmationState {
  mapping: ProgrammePcTeachingNameMapping
  teachingTargetId: string | null
  impact: TeachingNameMappingImpact
}

interface BulkConfirmationState {
  items: PreparedBulkMappingItem[]
  impact: TeachingNameMappingImpact
}

const PAGE_SIZE = 100

const lifecycleFilterValue = (filter: LifecycleFilter): boolean | undefined => {
  if (filter === 'active') {
    return true
  }
  if (filter === 'inactive') {
    return false
  }
  return undefined
}

const mappingActionLabel = (mapping: ProgrammePcTeachingNameMapping, targetId: string | null): string => {
  if (mapping.state === 'pending') {
    return 'Assign target'
  }
  return targetId === null ? 'Clear to pending' : 'Change mapping'
}

const impactSummary = (impact: TeachingNameMappingImpact): string =>
  `${impact.affectedEventCount} event${impact.affectedEventCount === 1 ? '' : 's'} and ${impact.affectedAttendanceCount} attendance record${impact.affectedAttendanceCount === 1 ? '' : 's'}`

export const PcSessionTypesPage = () => {
  const {
    reportingPeriodId,
    reportingPeriods,
    setReportingPeriodId,
    selectedProgrammeCode,
    setSelectedProgrammeCode,
    demoAdminId,
  } = useAppState()
  const { identity } = useAuth()

  const pcProgrammeScope = useMemo(
    () => identity?.role === 'programme_pc' ? identity.programmeScope : [],
    [identity],
  )
  const pcAdminId = identity?.role === 'programme_pc' ? identity.subjectId : demoAdminId
  const programmeScope = useMemo(
    () => resolvePcProgrammeScope(pcProgrammeScope, selectedProgrammeCode),
    [pcProgrammeScope, selectedProgrammeCode],
  )
  const selectedPcProgrammeCode = programmeScope.selectedProgrammeCode
  const selectedPeriod = useMemo(() => {
    const period = validatedReportingPeriod(reportingPeriods, reportingPeriodId)
    return period && isEffectivelyActiveReportingPeriod(period) ? period : undefined
  }, [reportingPeriodId, reportingPeriods])
  const selectedPeriodId = selectedPeriod?.id ?? ''
  const selectedScopeKey = selectedPcProgrammeCode && selectedPeriodId
    ? `${selectedPcProgrammeCode}:${selectedPeriodId}`
    : null

  const [mappingFilter, setMappingFilter] = useState<MappingFilter>('pending')
  const [mappingSearchInput, setMappingSearchInput] = useState('')
  const [mappingSearch, setMappingSearch] = useState('')
  const [postingFilterInput, setPostingFilterInput] = useState('')
  const [postingFilter, setPostingFilter] = useState('')
  const [rYearFilterInput, setRYearFilterInput] = useState('')
  const [rYearFilter, setRYearFilter] = useState('')
  const [mappingOffset, setMappingOffset] = useState(0)
  const [mappings, setMappings] = useState<ProgrammePcTeachingNameMapping[]>([])
  const [mappingTotal, setMappingTotal] = useState(0)
  const [mappingsLoading, setMappingsLoading] = useState(false)
  const [mappingsError, setMappingsError] = useState<string | null>(null)
  const [draftTargetIds, setDraftTargetIds] = useState<Record<string, string>>({})
  const [selectedMappingIds, setSelectedMappingIds] = useState<Set<string>>(new Set())
  const [mappingMutatingId, setMappingMutatingId] = useState<string | null>(null)
  const [bulkMutating, setBulkMutating] = useState(false)
  const [mappingFeedback, setMappingFeedback] = useState<string | null>(null)
  const [mappingFeedbackTone, setMappingFeedbackTone] = useState<FeedbackTone>('success')
  const [mappingFeedbackNeedsRefresh, setMappingFeedbackNeedsRefresh] = useState(false)
  const [singleConfirmation, setSingleConfirmation] = useState<SingleConfirmationState | null>(null)
  const [bulkConfirmation, setBulkConfirmation] = useState<BulkConfirmationState | null>(null)

  const [nameFilter, setNameFilter] = useState<LifecycleFilter>('active')
  const [nameSearchInput, setNameSearchInput] = useState('')
  const [nameSearch, setNameSearch] = useState('')
  const [nameOffset, setNameOffset] = useState(0)
  const [names, setNames] = useState<ProgrammePcTeachingName[]>([])
  const [nameTotal, setNameTotal] = useState(0)
  const [namesLoading, setNamesLoading] = useState(false)
  const [namesError, setNamesError] = useState<string | null>(null)
  const [nameFeedback, setNameFeedback] = useState<string | null>(null)
  const [nameFeedbackTone, setNameFeedbackTone] = useState<FeedbackTone>('success')
  const [nameFeedbackNeedsRefresh, setNameFeedbackNeedsRefresh] = useState(false)
  const [mutatingNameId, setMutatingNameId] = useState<string | null>(null)
  const [nameDrawerOpen, setNameDrawerOpen] = useState(false)
  const [nameDrawerMode, setNameDrawerMode] = useState<NameDrawerMode>('create')
  const [editingName, setEditingName] = useState<ProgrammePcTeachingName | null>(null)
  const [formTeachingName, setFormTeachingName] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [nameDrawerSaving, setNameDrawerSaving] = useState(false)
  const [interaction, setInteraction] = useState<PcSessionTypesInteractionSnapshot>({
    pendingAction: null,
    overlay: null,
  })

  const selectedScopeRef = useRef<string | null>(selectedScopeKey)
  const mappingListScopeKey = selectedScopeKey
    ? `${selectedScopeKey}:${mappingFilter}:${mappingSearch}:${postingFilter}:${rYearFilter}:${mappingOffset}`
    : null
  const namesListScopeKey = selectedScopeKey
    ? `${selectedScopeKey}:${nameFilter}:${nameSearch}:${nameOffset}`
    : null
  const mappingListScopeRef = useRef<string | null>(mappingListScopeKey)
  const namesListScopeRef = useRef<string | null>(namesListScopeKey)
  const mappingRequestFenceRef = useRef(createScopedRequestFence())
  const namesRequestFenceRef = useRef(createScopedRequestFence())
  const interactionCoordinatorRef = useRef(createPcSessionTypesInteractionCoordinator())

  const syncInteractionState = useCallback(() => {
    setInteraction(interactionCoordinatorRef.current.snapshot())
  }, [])
  const interactionLocked = interaction.pendingAction !== null || interaction.overlay !== null
  const interactionPending = interaction.pendingAction !== null
  const nameLifecyclePending = interaction.pendingAction === 'lifecycle-mutation'
  const mappingMutationPending = interaction.pendingAction === 'mapping-mutation'
  const bulkMutationPending = interaction.pendingAction === 'bulk-mutation'

  const beginInteraction = useCallback((action: PcSessionTypesPendingAction) => {
    const didBegin = interactionCoordinatorRef.current.tryBegin(action)
    if (didBegin) {
      syncInteractionState()
    }
    return didBegin
  }, [syncInteractionState])

  const transitionInteraction = useCallback((
    current: PcSessionTypesPendingAction,
    next: PcSessionTypesPendingAction,
  ) => {
    const didTransition = interactionCoordinatorRef.current.transitionPending(current, next)
    if (didTransition) {
      syncInteractionState()
    }
    return didTransition
  }, [syncInteractionState])

  const beginInteractionWithinOverlay = useCallback((
    overlay: PcSessionTypesOverlay,
    action: PcSessionTypesPendingAction,
  ) => {
    const didBegin = interactionCoordinatorRef.current.beginWithinOverlay(overlay, action)
    if (didBegin) {
      syncInteractionState()
    }
    return didBegin
  }, [syncInteractionState])

  const completeInteraction = useCallback((action: PcSessionTypesPendingAction) => {
    if (interactionCoordinatorRef.current.complete(action)) {
      syncInteractionState()
    }
  }, [syncInteractionState])

  const renderOverlay = useCallback((overlay: PcSessionTypesOverlay) => {
    setNameDrawerOpen(overlay === 'name-drawer')
    if (overlay !== 'single-confirmation') {
      setSingleConfirmation(null)
    }
    if (overlay !== 'bulk-confirmation') {
      setBulkConfirmation(null)
    }
    if (overlay !== 'name-drawer') {
      setEditingName(null)
      setNameDrawerSaving(false)
    }
  }, [])

  const closeActiveOverlay = useCallback((expectedOverlay?: PcSessionTypesOverlay) => {
    if (!interactionCoordinatorRef.current.closeOverlay(expectedOverlay)) {
      return false
    }
    setNameDrawerOpen(false)
    setSingleConfirmation(null)
    setBulkConfirmation(null)
    setEditingName(null)
    setNameDrawerSaving(false)
    syncInteractionState()
    return true
  }, [syncInteractionState])

  const replacePendingWithOverlay = useCallback((
    action: PcSessionTypesPendingAction,
    overlay: PcSessionTypesOverlay,
  ) => {
    const didReplace = interactionCoordinatorRef.current.replacePendingWithOverlay(action, overlay)
    if (didReplace) {
      renderOverlay(overlay)
      syncInteractionState()
    }
    return didReplace
  }, [renderOverlay, syncInteractionState])

  useEffect(() => {
    selectedScopeRef.current = selectedScopeKey
  }, [selectedScopeKey])

  useEffect(() => {
    mappingListScopeRef.current = mappingListScopeKey
  }, [mappingListScopeKey])

  useEffect(() => {
    namesListScopeRef.current = namesListScopeKey
  }, [namesListScopeKey])

  const clearScopeBoundState = useCallback(() => {
    mappingRequestFenceRef.current.invalidate()
    namesRequestFenceRef.current.invalidate()
    interactionCoordinatorRef.current.reset()
    syncInteractionState()
    setMappings([])
    setMappingTotal(0)
    setMappingsError(null)
    setDraftTargetIds({})
    setSelectedMappingIds(new Set())
    setMappingMutatingId(null)
    setBulkMutating(false)
    setMappingFeedback(null)
    setMappingFeedbackNeedsRefresh(false)
    setSingleConfirmation(null)
    setBulkConfirmation(null)
    setNames([])
    setNameTotal(0)
    setNamesError(null)
    setNameFeedback(null)
    setNameFeedbackNeedsRefresh(false)
    setMutatingNameId(null)
    setNameDrawerOpen(false)
    setEditingName(null)
    setNameDrawerSaving(false)
    setFormError(null)
  }, [syncInteractionState])

  useEffect(() => {
    if (selectedPcProgrammeCode && selectedProgrammeCode !== selectedPcProgrammeCode) {
      setSelectedProgrammeCode(selectedPcProgrammeCode)
    }
  }, [selectedPcProgrammeCode, selectedProgrammeCode, setSelectedProgrammeCode])

  useEffect(() => {
    let active = true
    void Promise.resolve().then(() => {
      if (!active) {
        return
      }
      clearScopeBoundState()
      setMappingOffset(0)
      setNameOffset(0)
    })
    return () => {
      active = false
    }
  }, [clearScopeBoundState, selectedScopeKey])

  const loadMappings = useCallback(async () => {
    const requestedScopeKey = selectedScopeRef.current
    const requestedListScopeKey = mappingListScopeRef.current
    const requestToken = mappingRequestFenceRef.current.begin(requestedListScopeKey)
    if (!selectedPcProgrammeCode || !selectedPeriod || !requestedScopeKey) {
      if (mappingRequestFenceRef.current.isCurrent(requestToken, mappingListScopeRef.current)) {
        setMappings([])
        setMappingTotal(0)
        setMappingsLoading(false)
      }
      return
    }

    setMappingsLoading(true)
    setMappingsError(null)
    try {
      const response = await listProgrammePcTeachingNameMappings({
        adminId: pcAdminId,
        programmeScope: pcProgrammeScope,
        reportingPeriodId: selectedPeriod.id,
        programmeCode: selectedPcProgrammeCode,
        postingCode: postingFilter,
        rYear: rYearFilter,
        state: mappingFilter === 'all' ? undefined : mappingFilter,
        search: mappingSearch,
        limit: PAGE_SIZE,
        offset: mappingOffset,
      })
      if (!mappingRequestFenceRef.current.isCurrent(requestToken, mappingListScopeRef.current)
        || selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      setMappings(response.items)
      setMappingTotal(response.total)
      setDraftTargetIds(Object.fromEntries(response.items.map((mapping) => [
        mapping.id,
        mapping.teachingTargetId ?? '',
      ])))
      setSelectedMappingIds(new Set())
    } catch (error) {
      if (!mappingRequestFenceRef.current.isCurrent(requestToken, mappingListScopeRef.current)
        || selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      setMappings([])
      setMappingTotal(0)
      setMappingsError(formatUserFacingApiError(error, {
        fallbackMessage: 'Unable to load Teaching Name mappings.',
      }))
    } finally {
      if (mappingRequestFenceRef.current.isCurrent(requestToken, mappingListScopeRef.current)
        && selectedScopeRef.current === requestedScopeKey) {
        setMappingsLoading(false)
      }
    }
  }, [
    mappingFilter,
    mappingOffset,
    mappingSearch,
    pcAdminId,
    pcProgrammeScope,
    postingFilter,
    rYearFilter,
    selectedPcProgrammeCode,
    selectedPeriod,
  ])

  const loadTeachingNames = useCallback(async () => {
    const requestedScopeKey = selectedScopeRef.current
    const requestedListScopeKey = namesListScopeRef.current
    const requestToken = namesRequestFenceRef.current.begin(requestedListScopeKey)
    if (!selectedPcProgrammeCode || !selectedPeriod || !requestedScopeKey) {
      if (namesRequestFenceRef.current.isCurrent(requestToken, namesListScopeRef.current)) {
        setNames([])
        setNameTotal(0)
        setNamesLoading(false)
      }
      return
    }

    setNamesLoading(true)
    setNamesError(null)
    try {
      const response = await listProgrammePcTeachingNames({
        adminId: pcAdminId,
        programmeScope: pcProgrammeScope,
        reportingPeriodId: selectedPeriod.id,
        programmeCode: selectedPcProgrammeCode,
        isActive: lifecycleFilterValue(nameFilter),
        search: nameSearch,
        limit: PAGE_SIZE,
        offset: nameOffset,
      })
      if (!namesRequestFenceRef.current.isCurrent(requestToken, namesListScopeRef.current)
        || selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      setNames(response.items)
      setNameTotal(response.total)
    } catch (error) {
      if (!namesRequestFenceRef.current.isCurrent(requestToken, namesListScopeRef.current)
        || selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      setNames([])
      setNameTotal(0)
      setNamesError(formatUserFacingApiError(error, {
        fallbackMessage: 'Unable to load Names of Teaching.',
      }))
    } finally {
      if (namesRequestFenceRef.current.isCurrent(requestToken, namesListScopeRef.current)
        && selectedScopeRef.current === requestedScopeKey) {
        setNamesLoading(false)
      }
    }
  }, [
    nameFilter,
    nameOffset,
    nameSearch,
    pcAdminId,
    pcProgrammeScope,
    selectedPcProgrammeCode,
    selectedPeriod,
  ])

  useEffect(() => {
    let active = true
    void Promise.resolve().then(() => active ? loadMappings() : undefined)
    return () => {
      active = false
    }
  }, [loadMappings])

  useEffect(() => {
    let active = true
    void Promise.resolve().then(() => active ? loadTeachingNames() : undefined)
    return () => {
      active = false
    }
  }, [loadTeachingNames])

  const canManageScope = Boolean(selectedPcProgrammeCode && selectedPeriod && programmeScope.mode !== 'none')
  const mappingPage = Math.floor(mappingOffset / PAGE_SIZE) + 1
  const mappingPageCount = Math.max(1, Math.ceil(mappingTotal / PAGE_SIZE))
  const namePage = Math.floor(nameOffset / PAGE_SIZE) + 1
  const namePageCount = Math.max(1, Math.ceil(nameTotal / PAGE_SIZE))
  const selectedMappingCount = selectedMappingIds.size

  const setMappingFeedbackState = (message: string, tone: FeedbackTone, needsRefresh = false) => {
    setMappingFeedback(message)
    setMappingFeedbackTone(tone)
    setMappingFeedbackNeedsRefresh(needsRefresh)
  }

  const resolveMappingMutationFailure = (error: unknown, fallback: string) => {
    if (isTeachingNameMappingRevisionConflict(error)) {
      setSelectedMappingIds(new Set())
      closeActiveOverlay()
      setMappingFeedbackState('This mapping changed by someone else. Refresh the queue and retry.', 'warning', true)
      return
    }
    if (error instanceof ApiRequestError && error.status === 409) {
      closeActiveOverlay()
      if (error.message.includes('conflicting durations')) {
        setMappingFeedbackState(`${error.message} No mapping changes were applied.`, 'warning', true)
        return
      }
      setMappingFeedbackState('This mapping could not be applied. Refresh the queue and retry.', 'warning', true)
      return
    }
    closeActiveOverlay()
    setMappingFeedbackState(formatUserFacingApiError(error, { fallbackMessage: fallback }), 'warning')
  }

  const mergeReturnedMapping = (updated: ProgrammePcTeachingNameMapping) => {
    setMappings((current) => current.map((mapping) => mapping.id === updated.id ? updated : mapping))
    setDraftTargetIds((current) => ({ ...current, [updated.id]: updated.teachingTargetId ?? '' }))
  }

  const executeSingleMapping = async (
    mapping: ProgrammePcTeachingNameMapping,
    teachingTargetId: string | null,
    confirmImpact: boolean,
  ) => {
    const requestedScopeKey = selectedScopeRef.current
    setMappingMutatingId(mapping.id)
    setMappingsError(null)
    try {
      const response = await applyProgrammePcTeachingNameMapping({
        adminId: pcAdminId,
        programmeScope: pcProgrammeScope,
        mappingId: mapping.id,
        expectedRevision: mapping.revision,
        teachingTargetId,
        confirmImpact,
      })
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      mergeReturnedMapping(response)
      setSelectedMappingIds(new Set())
      closeActiveOverlay('single-confirmation')
      setMappingFeedbackState(
        `Mapping updated. Existing event durations and end times were recalculated for the exact Teaching Name and posting. Attendance submissions were preserved. ${impactSummary(response.impact)} were reviewed.`,
        'success',
      )
      await loadMappings()
    } catch (error) {
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      const conflictImpact = mappingImpactFromConflict(error)
      if (conflictImpact && !confirmImpact) {
        if (replacePendingWithOverlay('mapping-mutation', 'single-confirmation')) {
          setSingleConfirmation({ mapping, teachingTargetId, impact: conflictImpact })
        }
        return
      }
      resolveMappingMutationFailure(error, 'The mapping could not be updated.')
    } finally {
      if (selectedScopeRef.current === requestedScopeKey) {
        setMappingMutatingId(null)
      }
      completeInteraction('mapping-mutation')
    }
  }

  const previewAndApplySingleMapping = async (mapping: ProgrammePcTeachingNameMapping) => {
    if (!beginInteraction('mapping-impact-preview')) {
      return
    }
    const targetId = draftTargetIds[mapping.id] ?? mapping.teachingTargetId ?? ''
    const teachingTargetId = targetId || null
    if (teachingTargetId === mapping.teachingTargetId) {
      setMappingFeedbackState('Choose a different exact target, or clear an existing mapping to return it to pending.', 'warning')
      completeInteraction('mapping-impact-preview')
      return
    }
    if (teachingTargetId && !targetOptionsForMapping(mapping).some((target) => target.id === teachingTargetId)) {
      setMappingFeedbackState('Select an exact target from this mapping row.', 'warning')
      completeInteraction('mapping-impact-preview')
      return
    }

    const requestedScopeKey = selectedScopeRef.current
    setMappingMutatingId(mapping.id)
    setMappingsError(null)
    try {
      const impact = await getProgrammePcTeachingNameMappingImpact({
        adminId: pcAdminId,
        programmeScope: pcProgrammeScope,
        mappingId: mapping.id,
        expectedRevision: mapping.revision,
        teachingTargetId,
      })
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      if (impact.affectedEventCount > 0 || impact.affectedAttendanceCount > 0) {
        if (replacePendingWithOverlay('mapping-impact-preview', 'single-confirmation')) {
          setSingleConfirmation({ mapping, teachingTargetId, impact })
        }
        return
      }
      if (!transitionInteraction('mapping-impact-preview', 'mapping-mutation')) {
        return
      }
      await executeSingleMapping(mapping, teachingTargetId, false)
    } catch (error) {
      if (selectedScopeRef.current === requestedScopeKey) {
        resolveMappingMutationFailure(error, 'Unable to preview this mapping change.')
      }
    } finally {
      if (selectedScopeRef.current === requestedScopeKey) {
        setMappingMutatingId(null)
      }
      completeInteraction('mapping-impact-preview')
    }
  }

  const executeBulkMappings = async (items: PreparedBulkMappingItem[], confirmImpact: boolean) => {
    const requestedScopeKey = selectedScopeRef.current
    setBulkMutating(true)
    setMappingsError(null)
    try {
      const result = await applyProgrammePcTeachingNameMappingBulk({
        adminId: pcAdminId,
        programmeScope: pcProgrammeScope,
        items: items.map((item) => ({ ...item, confirmImpact })),
      })
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      setSelectedMappingIds(new Set())
      closeActiveOverlay('bulk-confirmation')
      setMappingFeedbackState(
        `Atomic bulk mapping updated ${result.updatedCount} row${result.updatedCount === 1 ? '' : 's'} (${result.mappedCount} mapped, ${result.pendingCount} pending). Existing event durations and end times were recalculated; attendance submissions were preserved.`,
        'success',
      )
      await loadMappings()
    } catch (error) {
      if (selectedScopeRef.current === requestedScopeKey) {
        resolveMappingMutationFailure(error, 'The bulk mapping could not be applied. No rows were changed.')
      }
    } finally {
      if (selectedScopeRef.current === requestedScopeKey) {
        setBulkMutating(false)
      }
      completeInteraction('bulk-mutation')
    }
  }

  const previewAndApplyBulkMappings = async () => {
    if (!beginInteraction('bulk-impact-preview')) {
      return
    }
    const prepared = prepareBulkMappingChanges(mappings, selectedMappingIds, draftTargetIds)
    if (prepared.kind === 'invalid') {
      setMappingFeedbackState(prepared.message, 'warning')
      completeInteraction('bulk-impact-preview')
      return
    }

    const requestedScopeKey = selectedScopeRef.current
    setBulkMutating(true)
    setMappingsError(null)
    try {
      const impacts = await Promise.all(prepared.items.map((item) =>
        getProgrammePcTeachingNameMappingImpact({
          adminId: pcAdminId,
          programmeScope: pcProgrammeScope,
          mappingId: item.mappingId,
          expectedRevision: item.expectedRevision,
          teachingTargetId: item.teachingTargetId,
        })))
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      const impact = impacts.reduce<TeachingNameMappingImpact>((total, value) => ({
        affectedEventCount: total.affectedEventCount + value.affectedEventCount,
        affectedAttendanceCount: total.affectedAttendanceCount + value.affectedAttendanceCount,
      }), { affectedEventCount: 0, affectedAttendanceCount: 0 })
      if (impact.affectedEventCount > 0 || impact.affectedAttendanceCount > 0) {
        if (replacePendingWithOverlay('bulk-impact-preview', 'bulk-confirmation')) {
          setBulkConfirmation({ items: prepared.items, impact })
        }
        return
      }
      if (!transitionInteraction('bulk-impact-preview', 'bulk-mutation')) {
        return
      }
      await executeBulkMappings(prepared.items, false)
    } catch (error) {
      if (selectedScopeRef.current === requestedScopeKey) {
        resolveMappingMutationFailure(error, 'Unable to preview the bulk mapping change.')
      }
    } finally {
      if (selectedScopeRef.current === requestedScopeKey) {
        setBulkMutating(false)
      }
      completeInteraction('bulk-impact-preview')
    }
  }

  const toggleMappingSelection = (mappingId: string) => {
    const interactionState = interactionCoordinatorRef.current.snapshot()
    if (interactionState.pendingAction !== null || interactionState.overlay !== null) {
      return
    }
    setSelectedMappingIds((current) => {
      const next = new Set(current)
      if (next.has(mappingId)) {
        next.delete(mappingId)
      } else if (next.size < MAX_BULK_MAPPING_ITEMS) {
        next.add(mappingId)
      }
      return next
    })
    setMappingFeedback(null)
    setMappingFeedbackNeedsRefresh(false)
  }

  const toggleAllMappings = () => {
    const interactionState = interactionCoordinatorRef.current.snapshot()
    if (interactionState.pendingAction !== null || interactionState.overlay !== null) {
      return
    }
    if (selectedMappingIds.size === mappings.length) {
      setSelectedMappingIds(new Set())
      return
    }
    setSelectedMappingIds(new Set(mappings.slice(0, MAX_BULK_MAPPING_ITEMS).map((mapping) => mapping.id)))
  }

  const openNameDrawer = (mode: NameDrawerMode, name?: ProgrammePcTeachingName) => {
    if (!canManageScope || !interactionCoordinatorRef.current.openOverlay('name-drawer')) {
      return
    }
    renderOverlay('name-drawer')
    setNameDrawerMode(mode)
    setEditingName(name ?? null)
    setFormTeachingName(name?.teachingName ?? '')
    setFormError(null)
    syncInteractionState()
  }

  const closeNameDrawer = () => {
    if (interactionCoordinatorRef.current.snapshot().pendingAction !== null) {
      return
    }
    closeActiveOverlay('name-drawer')
  }

  const submitNameForm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const teachingName = formTeachingName.trim()
    if (!selectedPcProgrammeCode || !selectedPeriod || !teachingName) {
      setFormError('Name of Teaching is required within the selected programme and reporting period.')
      return
    }
    if (!beginInteractionWithinOverlay('name-drawer', 'lifecycle-mutation')) {
      return
    }

    const requestedScopeKey = selectedScopeRef.current
    setNameDrawerSaving(true)
    setFormError(null)
    try {
      if (nameDrawerMode === 'edit' && editingName) {
        await renameProgrammePcTeachingName({
          adminId: pcAdminId,
          programmeScope: pcProgrammeScope,
          teachingNameId: editingName.id,
          teachingName,
          expectedRevision: editingName.revision,
        })
      } else {
        await createProgrammePcTeachingName({
          adminId: pcAdminId,
          programmeScope: pcProgrammeScope,
          reportingPeriodId: selectedPeriod.id,
          programmeCode: selectedPcProgrammeCode,
          teachingName,
        })
      }
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      closeActiveOverlay('name-drawer')
      setNameFeedbackTone('success')
      setNameFeedback(nameDrawerMode === 'edit' ? 'Name of Teaching renamed.' : 'Name of Teaching created.')
      setNameFeedbackNeedsRefresh(false)
      await Promise.all([loadTeachingNames(), loadMappings()])
    } catch (error) {
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      const result = resolveTeachingNameLifecycleError(
        error,
        nameDrawerMode === 'edit'
          ? 'Name of Teaching could not be updated. Try again.'
          : 'Name of Teaching could not be created. Try again.',
      )
      setFormError(result.message)
      setNameFeedbackNeedsRefresh(result.needsRefresh)
    } finally {
      if (selectedScopeRef.current === requestedScopeKey) {
        setNameDrawerSaving(false)
      }
      completeInteraction('lifecycle-mutation')
    }
  }

  const runLifecycleAction = async (
    name: ProgrammePcTeachingName,
    action: 'deactivate' | 'reactivate' | 'delete',
  ) => {
    if (!beginInteraction('lifecycle-mutation')) {
      return
    }
    const requestedScopeKey = selectedScopeRef.current
    setMutatingNameId(name.id)
    setNamesError(null)
    setNameFeedback(null)
    try {
      if (action === 'deactivate') {
        await deactivateProgrammePcTeachingName({
          adminId: pcAdminId,
          programmeScope: pcProgrammeScope,
          teachingNameId: name.id,
          expectedRevision: name.revision,
        })
      } else if (action === 'reactivate') {
        await reactivateProgrammePcTeachingName({
          adminId: pcAdminId,
          programmeScope: pcProgrammeScope,
          teachingNameId: name.id,
          expectedRevision: name.revision,
        })
      } else {
        await deleteProgrammePcTeachingName({
          adminId: pcAdminId,
          programmeScope: pcProgrammeScope,
          teachingNameId: name.id,
          expectedRevision: name.revision,
        })
      }
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      setNameFeedbackTone('success')
      setNameFeedback(
        action === 'deactivate'
          ? 'Name of Teaching deactivated.'
          : action === 'reactivate'
            ? 'Name of Teaching reactivated.'
            : 'Unused Name of Teaching deleted.',
      )
      setNameFeedbackNeedsRefresh(false)
      await Promise.all([loadTeachingNames(), loadMappings()])
    } catch (error) {
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      const result = resolveTeachingNameLifecycleError(error, 'Name of Teaching could not be updated. Try again.')
      setNameFeedbackTone('warning')
      setNameFeedback(result.message)
      setNameFeedbackNeedsRefresh(result.needsRefresh)
    } finally {
      if (selectedScopeRef.current === requestedScopeKey) {
        setMutatingNameId(null)
      }
      completeInteraction('lifecycle-mutation')
    }
  }

  const handleProgrammeChange = (programmeCode: string) => {
    const interactionState = interactionCoordinatorRef.current.snapshot()
    if (interactionState.pendingAction !== null || interactionState.overlay !== null) {
      return
    }
    clearScopeBoundState()
    setMappingOffset(0)
    setNameOffset(0)
    setSelectedProgrammeCode(programmeCode)
  }

  const handlePeriodChange = (periodId: string) => {
    const interactionState = interactionCoordinatorRef.current.snapshot()
    if (interactionState.pendingAction !== null || interactionState.overlay !== null) {
      return
    }
    clearScopeBoundState()
    setMappingOffset(0)
    setNameOffset(0)
    setReportingPeriodId(periodId)
  }

  return (
    <div className="page pc-session-types-page">
      <PageHero
        title="Map Names of Teaching to Session Types"
        subtitle="Manage the shared Teaching Name pool and map each exact posting and R-year scope to a TTF session-type target."
        actions={
          <div className="pc-session-types-hero-actions">
            <button
              type="button"
              className="button button-secondary"
              onClick={() => {
                void Promise.all([loadMappings(), loadTeachingNames()])
              }}
              disabled={!canManageScope || mappingsLoading || namesLoading || interactionLocked}
            >
              <IconRefresh size={14} />
              Refresh
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={() => openNameDrawer('create')}
              disabled={!canManageScope || interactionLocked}
              title={canManageScope ? 'Create a Name of Teaching.' : 'Select an active reporting period and an in-scope programme first.'}
            >
              <IconPlus size={15} />
              Update Name of Teaching
            </button>
          </div>
        }
      />

      <section className="card pc-session-types-scope-card" aria-label="Programme and reporting period scope">
        <div className="pc-session-types-scope-header">
          <div>
            <h2>Scope</h2>
            <p>Programme options are limited to your current Programme PC scope.</p>
          </div>
        </div>
        {programmeScope.mode === 'none' ? (
          <div className="pc-session-types-empty-state" role="status">
            <h3>No programme scope</h3>
            <p>You do not currently have a persisted Programme PC scope for Teaching Name management.</p>
          </div>
        ) : (
          <div className="pc-session-types-scope-controls">
            {programmeScope.mode === 'locked' ? (
              <span className="scope-chip">Programme: {programmeScope.selectedProgrammeLabel}</span>
            ) : (
              <label className="pc-session-types-select">
                <span>Programme</span>
                <select
                  value={selectedPcProgrammeCode}
                  onChange={(event) => handleProgrammeChange(event.target.value)}
                  aria-label="Programme"
                  disabled={interactionLocked}
                >
                  {programmeScope.programmeOptions.map((programme) => (
                    <option key={programme.code} value={programme.code}>{programme.label}</option>
                  ))}
                </select>
              </label>
            )}
            <label className="pc-session-types-select">
              <span>Reporting period</span>
              <select
                value={selectedPeriodId}
                onChange={(event) => handlePeriodChange(event.target.value)}
                aria-label="Reporting period"
                disabled={interactionLocked}
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
        )}
      </section>

      {programmeScope.mode !== 'none' && !selectedPeriod ? (
        <section className="card pc-session-types-empty-state" role="status">
          <h3>Select an active reporting period</h3>
          <p>Mapping and Teaching Name changes are available only within a selected active reporting period.</p>
        </section>
      ) : null}

      {canManageScope ? (
        <>
          <section className="card pc-session-types-mapping-card" aria-label="Teaching Name mapping queue">
            <div className="section-header pc-session-types-section-header">
              <div>
                <h2>Mapping queue</h2>
                <p>Pending names remain available for events and attendance. They need an exact target before later compliance classification can occur.</p>
              </div>
              <span className="inline-muted">{mappingTotal} mapping{mappingTotal === 1 ? '' : 's'}</span>
            </div>

            <div className="inline-callout callout-warning pc-session-types-pending-callout" role="status">
              <span>A mapping updates existing pool-backed event duration and end time for this exact scope. Attendance submissions and historical Name of Teaching text remain unchanged.</span>
            </div>

            <form
              className="pc-session-types-filters"
              onSubmit={(event) => {
                event.preventDefault()
                setMappingOffset(0)
                setMappingSearch(mappingSearchInput)
                setPostingFilter(postingFilterInput)
                setRYearFilter(rYearFilterInput)
              }}
            >
              <div className="filter-row" aria-label="Mapping state">
                {(['pending', 'mapped', 'all'] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={`filter-chip ${mappingFilter === value ? 'active' : ''}`}
                    aria-pressed={mappingFilter === value}
                    aria-label={value === 'all' ? 'Show all mappings' : `Show ${value} mappings`}
                    onClick={() => {
                      setMappingFilter(value)
                      setMappingOffset(0)
                    }}
                    disabled={interactionLocked}
                  >
                    {value === 'all' ? 'All' : value[0].toUpperCase() + value.slice(1)}
                  </button>
                ))}
              </div>
              <label className="pc-session-types-search">
                <span>Search Names of Teaching</span>
                <input
                  type="search"
                  value={mappingSearchInput}
                  onChange={(event) => setMappingSearchInput(event.target.value)}
                  placeholder="Search by name"
                  disabled={interactionLocked}
                />
              </label>
              <label className="pc-session-types-short-filter">
                <span>Posting</span>
                <input value={postingFilterInput} onChange={(event) => setPostingFilterInput(event.target.value)} disabled={interactionLocked} />
              </label>
              <label className="pc-session-types-short-filter">
                <span>R-year</span>
                <input value={rYearFilterInput} onChange={(event) => setRYearFilterInput(event.target.value)} disabled={interactionLocked} />
              </label>
              <button type="submit" className="button button-secondary" disabled={interactionLocked}>Apply filters</button>
            </form>

            {mappingFeedback ? (
              <div className={`inline-callout ${mappingFeedbackTone === 'success' ? 'callout-success' : 'callout-warning'} pc-session-types-feedback`} role={mappingFeedbackTone === 'warning' ? 'alert' : 'status'}>
                <span>{mappingFeedback}</span>
                {mappingFeedbackNeedsRefresh ? (
                  <button type="button" className="button button-ghost" onClick={() => void loadMappings()} disabled={interactionLocked}>
                    <IconRefresh size={14} />
                    Refresh queue
                  </button>
                ) : null}
              </div>
            ) : null}
            {mappingsError ? (
              <div className="inline-callout callout-error pc-session-types-feedback" role="alert">
                <span>{mappingsError}</span>
                <button type="button" className="button button-ghost" onClick={() => void loadMappings()} disabled={interactionLocked}>
                  <IconRefresh size={14} />
                  Retry
                </button>
              </div>
            ) : null}

            {selectedMappingCount > 0 ? (
              <div className="pc-session-types-bulk-toolbar" aria-label="Bulk mapping actions">
                <span>{selectedMappingCount} selected</span>
                <span className="inline-muted">Bulk changes are atomic: if any selected row is invalid or stale, no row is applied.</span>
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => void previewAndApplyBulkMappings()}
                  disabled={interactionLocked}
                >
                  {bulkMutating ? 'Applying…' : 'Apply prepared changes'}
                </button>
                <button type="button" className="button button-ghost" onClick={() => setSelectedMappingIds(new Set())} disabled={interactionLocked}>
                  Clear selection
                </button>
              </div>
            ) : null}

            <div className="table-wrap pc-session-types-table-wrap">
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>
                        <input
                          type="checkbox"
                          aria-label="Select all visible mappings for bulk change"
                          checked={mappings.length > 0 && selectedMappingCount === mappings.length}
                          onChange={toggleAllMappings}
                          disabled={mappingsLoading || interactionLocked}
                        />
                      </th>
                      <th>Name of Teaching</th>
                      <th>Posting</th>
                      <th>R-year</th>
                      <th>State</th>
                      <th>Current target</th>
                      <th>Exact session type target</th>
                      <th>Revision</th>
                      <th>Action</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mappingsLoading ? (
                      <tr><td colSpan={9}>Loading Teaching Name mappings...</td></tr>
                    ) : mappings.length === 0 ? (
                      <tr><td colSpan={9}>No mappings match this scope.</td></tr>
                    ) : mappings.map((mapping) => {
                      const draftTargetId = draftTargetIds[mapping.id] ?? mapping.teachingTargetId ?? ''
                      const selectedTargetId = draftTargetId || null
                      const isMutating = interactionLocked || mappingMutatingId === mapping.id || bulkMutating
                      return (
                        <tr key={mapping.id}>
                          <td>
                            <input
                              type="checkbox"
                              aria-label={`Select ${mapping.teachingName} mapping for ${mapping.postingCode} ${mapping.rYear}`}
                              checked={selectedMappingIds.has(mapping.id)}
                              onChange={() => toggleMappingSelection(mapping.id)}
                              disabled={isMutating}
                            />
                          </td>
                          <td className="safe-wrap">
                            <strong>{mapping.teachingName}</strong>
                            {!mapping.teachingNameIsActive ? <span className="inline-muted"> Inactive name</span> : null}
                          </td>
                          <td className="mono">{mapping.postingCode}</td>
                          <td>{mapping.rYear}</td>
                          <td><span className={`status-badge ${mapping.state === 'mapped' ? 'status-badge-success' : 'status-badge-warning'}`}>{mapping.state === 'mapped' ? 'Mapped' : 'Pending'}</span></td>
                          <td className="safe-wrap">{mapping.target ? targetOptionLabel(mapping.target) : 'No target assigned'}</td>
                          <td>
                            <label className="pc-session-types-target-select">
                              <span className="sr-only">Exact target for {mapping.teachingName}</span>
                              <select
                                value={draftTargetId}
                                onChange={(event) => setDraftTargetIds((current) => ({ ...current, [mapping.id]: event.target.value }))}
                                disabled={isMutating}
                              >
                                <option value="">{mapping.state === 'mapped' ? 'Clear to pending' : 'Choose exact target'}</option>
                                {targetOptionsForMapping(mapping).map((target) => (
                                  <option key={target.id} value={target.id}>{targetOptionLabel(target)}</option>
                                ))}
                              </select>
                            </label>
                          </td>
                          <td className="mono">{mapping.revision}</td>
                          <td>
                            <button
                              type="button"
                              className="button button-secondary"
                              onClick={() => void previewAndApplySingleMapping(mapping)}
                              disabled={isMutating || selectedTargetId === mapping.teachingTargetId}
                            >
                              {mappingMutatingId === mapping.id ? 'Saving…' : mappingActionLabel(mapping, selectedTargetId)}
                            </button>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="pc-session-types-mobile-list" aria-label="Teaching Name mapping cards">
              {mappingsLoading ? <div className="mobile-record-card">Loading Teaching Name mappings...</div> : null}
              {!mappingsLoading && mappings.length === 0 ? <div className="mobile-record-card">No mappings match this scope.</div> : null}
              {!mappingsLoading ? mappings.map((mapping) => {
                const draftTargetId = draftTargetIds[mapping.id] ?? mapping.teachingTargetId ?? ''
                const selectedTargetId = draftTargetId || null
                const isMutating = interactionLocked || mappingMutatingId === mapping.id || bulkMutating
                return (
                  <article key={mapping.id} className="mobile-record-card pc-session-types-mobile-card">
                    <div className="pc-session-types-mobile-heading">
                      <div>
                        <strong className="safe-wrap">{mapping.teachingName}</strong>
                        <p>{mapping.postingCode} · {mapping.rYear} · Revision {mapping.revision}</p>
                      </div>
                      <span className={`status-badge ${mapping.state === 'mapped' ? 'status-badge-success' : 'status-badge-warning'}`}>{mapping.state === 'mapped' ? 'Mapped' : 'Pending'}</span>
                    </div>
                    <p className="pc-session-types-current-target"><strong>Current target:</strong> {mapping.target ? targetOptionLabel(mapping.target) : 'No target assigned'}</p>
                    <label className="pc-session-types-target-select">
                      <span>Exact session type target</span>
                      <select
                        value={draftTargetId}
                        onChange={(event) => setDraftTargetIds((current) => ({ ...current, [mapping.id]: event.target.value }))}
                        disabled={isMutating}
                      >
                        <option value="">{mapping.state === 'mapped' ? 'Clear to pending' : 'Choose exact target'}</option>
                        {targetOptionsForMapping(mapping).map((target) => (
                          <option key={target.id} value={target.id}>{targetOptionLabel(target)}</option>
                        ))}
                      </select>
                    </label>
                    <div className="pc-session-types-mobile-actions">
                      <label className="pc-session-types-checkbox-label">
                        <input
                          type="checkbox"
                          checked={selectedMappingIds.has(mapping.id)}
                          onChange={() => toggleMappingSelection(mapping.id)}
                          disabled={isMutating}
                        />
                        Select for bulk change
                      </label>
                      <button
                        type="button"
                        className="button button-primary"
                        onClick={() => void previewAndApplySingleMapping(mapping)}
                        disabled={isMutating || selectedTargetId === mapping.teachingTargetId}
                      >
                        {mappingMutatingId === mapping.id ? 'Saving…' : mappingActionLabel(mapping, selectedTargetId)}
                      </button>
                    </div>
                  </article>
                )
              }) : null}
            </div>

            {mappingTotal > PAGE_SIZE ? (
              <div className="pc-session-types-pagination" aria-label="Mapping pagination">
                <span>Page {mappingPage} of {mappingPageCount}</span>
                <button type="button" className="button button-secondary" disabled={mappingOffset === 0 || mappingsLoading || interactionLocked} onClick={() => setMappingOffset(Math.max(0, mappingOffset - PAGE_SIZE))}>Previous</button>
                <button type="button" className="button button-secondary" disabled={mappingOffset + PAGE_SIZE >= mappingTotal || mappingsLoading || interactionLocked} onClick={() => setMappingOffset(mappingOffset + PAGE_SIZE)}>Next</button>
              </div>
            ) : null}
          </section>

          <section className="card pc-session-types-names-card" aria-label="Teaching Name management">
            <div className="section-header pc-session-types-section-header">
              <div>
                <h2>Names of Teaching</h2>
                <p>Lifecycle actions apply only to the selected programme and reporting period. Deleting an in-use name is not available here.</p>
              </div>
              <button type="button" className="button button-secondary" onClick={() => void loadTeachingNames()} disabled={namesLoading || interactionLocked}>
                <IconRefresh size={14} />
                Refresh names
              </button>
            </div>

            <form
              className="pc-session-types-filters"
              onSubmit={(event) => {
                event.preventDefault()
                setNameOffset(0)
                setNameSearch(nameSearchInput)
              }}
            >
              <div className="filter-row" aria-label="Teaching Name lifecycle state">
                {(['active', 'inactive', 'all'] as const).map((value) => (
                  <button
                    key={value}
                    type="button"
                    className={`filter-chip ${nameFilter === value ? 'active' : ''}`}
                    aria-pressed={nameFilter === value}
                    aria-label={value === 'all' ? 'Show all Names of Teaching' : `Show ${value} Names of Teaching`}
                    onClick={() => {
                      setNameFilter(value)
                      setNameOffset(0)
                    }}
                    disabled={interactionLocked}
                  >
                    {value[0].toUpperCase() + value.slice(1)}
                  </button>
                ))}
              </div>
              <label className="pc-session-types-search">
                <span>Search Names of Teaching</span>
                <input
                  type="search"
                  value={nameSearchInput}
                  onChange={(event) => setNameSearchInput(event.target.value)}
                  placeholder="Search by name"
                  disabled={interactionLocked}
                />
              </label>
              <button type="submit" className="button button-secondary" disabled={interactionLocked}>Search</button>
            </form>

            {nameFeedback ? (
              <div className={`inline-callout ${nameFeedbackTone === 'success' ? 'callout-success' : 'callout-warning'} pc-session-types-feedback`} role={nameFeedbackTone === 'warning' ? 'alert' : 'status'}>
                <span>{nameFeedback}</span>
                {nameFeedbackNeedsRefresh ? (
                  <button type="button" className="button button-ghost" onClick={() => void loadTeachingNames()} disabled={interactionLocked}>
                    <IconRefresh size={14} />
                    Refresh names
                  </button>
                ) : null}
              </div>
            ) : null}
            {namesError ? (
              <div className="inline-callout callout-error pc-session-types-feedback" role="alert">
                <span>{namesError}</span>
                <button type="button" className="button button-ghost" onClick={() => void loadTeachingNames()} disabled={interactionLocked}>
                  <IconRefresh size={14} />
                  Retry
                </button>
              </div>
            ) : null}

            <div className="table-wrap pc-session-types-names-table-wrap">
              <div className="table-scroll">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Name of Teaching</th>
                      <th>State</th>
                      <th>Revision</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {namesLoading ? (
                      <tr><td colSpan={4}>Loading Names of Teaching...</td></tr>
                    ) : names.length === 0 ? (
                      <tr><td colSpan={4}>No Names of Teaching match this scope.</td></tr>
                    ) : names.map((name) => {
                      const isMutating = interactionLocked || mutatingNameId === name.id
                      return (
                        <tr key={name.id}>
                          <td className="safe-wrap">{name.teachingName}</td>
                          <td><span className={`status-badge ${name.isActive ? 'status-badge-success' : 'status-badge-neutral'}`}>{name.isActive ? 'Active' : 'Inactive'}</span></td>
                          <td className="mono">{name.revision}</td>
                          <td>
                            <div className="pc-session-types-name-actions">
                              <button type="button" className="button button-ghost" onClick={() => openNameDrawer('edit', name)} disabled={isMutating}>Rename</button>
                              <button
                                type="button"
                                className="button button-ghost"
                                onClick={() => void runLifecycleAction(name, name.isActive ? 'deactivate' : 'reactivate')}
                                disabled={isMutating}
                              >
                                {name.isActive ? 'Deactivate' : 'Reactivate'}
                              </button>
                              <button type="button" className="button button-ghost danger" onClick={() => void runLifecycleAction(name, 'delete')} disabled={isMutating}>Delete unused</button>
                            </div>
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="pc-session-types-names-mobile-list" aria-label="Teaching Name cards">
              {namesLoading ? <div className="mobile-record-card">Loading Names of Teaching...</div> : null}
              {!namesLoading && names.length === 0 ? <div className="mobile-record-card">No Names of Teaching match this scope.</div> : null}
              {!namesLoading ? names.map((name) => {
                const isMutating = interactionLocked || mutatingNameId === name.id
                return (
                  <article key={name.id} className="mobile-record-card pc-session-types-mobile-card">
                    <div className="pc-session-types-mobile-heading">
                      <strong className="safe-wrap">{name.teachingName}</strong>
                      <span className={`status-badge ${name.isActive ? 'status-badge-success' : 'status-badge-neutral'}`}>{name.isActive ? 'Active' : 'Inactive'}</span>
                    </div>
                    <p>Revision {name.revision}</p>
                    <div className="pc-session-types-mobile-actions">
                      <button type="button" className="button button-secondary" onClick={() => openNameDrawer('edit', name)} disabled={isMutating}>Rename</button>
                      <button type="button" className="button button-secondary" onClick={() => void runLifecycleAction(name, name.isActive ? 'deactivate' : 'reactivate')} disabled={isMutating}>{name.isActive ? 'Deactivate' : 'Reactivate'}</button>
                      <button type="button" className="button button-ghost danger" onClick={() => void runLifecycleAction(name, 'delete')} disabled={isMutating}>Delete unused</button>
                    </div>
                  </article>
                )
              }) : null}
            </div>

            {nameTotal > PAGE_SIZE ? (
              <div className="pc-session-types-pagination" aria-label="Teaching Name pagination">
                <span>Page {namePage} of {namePageCount}</span>
                <button type="button" className="button button-secondary" disabled={nameOffset === 0 || namesLoading || interactionLocked} onClick={() => setNameOffset(Math.max(0, nameOffset - PAGE_SIZE))}>Previous</button>
                <button type="button" className="button button-secondary" disabled={nameOffset + PAGE_SIZE >= nameTotal || namesLoading || interactionLocked} onClick={() => setNameOffset(nameOffset + PAGE_SIZE)}>Next</button>
              </div>
            ) : null}
          </section>
        </>
      ) : null}

      <DetailDrawer
        title="Update Name of Teaching"
        open={interaction.overlay === 'name-drawer' && nameDrawerOpen}
        onClose={closeNameDrawer}
        closeDisabled={interactionPending}
        busy={nameLifecyclePending}
        footer={
          <>
            <button type="button" className="button button-ghost" onClick={closeNameDrawer} disabled={interactionPending}>Cancel</button>
            <button type="submit" className="button button-primary" form="pc-teaching-name-form" disabled={interactionPending}>
              {nameDrawerSaving ? 'Saving' : nameDrawerMode === 'edit' ? 'Save changes' : 'Create Name of Teaching'}
            </button>
          </>
        }
      >
        <form id="pc-teaching-name-form" className="secretary-form-grid" onSubmit={(event) => void submitNameForm(event)}>
          <div className="secretary-teaching-names-form-context" aria-label="Selected scope">
            <span>Programme: {selectedPcProgrammeCode}</span>
            <span>Reporting period: {selectedPeriod?.label ?? '-'}</span>
          </div>
          <label>
            Name of Teaching
            <input
              value={formTeachingName}
              onChange={(event) => setFormTeachingName(event.target.value)}
              autoFocus
              maxLength={200}
              disabled={interactionPending}
            />
          </label>
          {formError ? <div className="inline-callout callout-error" role="alert">{formError}</div> : null}
        </form>
      </DetailDrawer>

      <DetailDrawer
        title="Confirm mapping change"
        open={interaction.overlay === 'single-confirmation' && singleConfirmation !== null}
        onClose={() => closeActiveOverlay('single-confirmation')}
        closeDisabled={interactionPending}
        busy={mappingMutationPending}
        footer={
          <>
            <button type="button" className="button button-ghost" onClick={() => closeActiveOverlay('single-confirmation')} disabled={interactionPending}>Cancel</button>
            <button
              type="button"
              className="button button-primary"
              onClick={() => {
                const confirmation = singleConfirmation
                if (confirmation && beginInteractionWithinOverlay('single-confirmation', 'mapping-mutation')) {
                  void executeSingleMapping(
                    confirmation.mapping,
                    confirmation.teachingTargetId,
                    true,
                  )
                }
              }}
              disabled={interactionPending}
            >
              Confirm mapping change
            </button>
          </>
        }
      >
        {singleConfirmation ? (
          <div className="pc-session-types-confirmation" role="status">
            <p>This change may affect {impactSummary(singleConfirmation.impact)}. Only these aggregate counts are shown.</p>
            <p>Confirm to recalculate duration and end time for existing events in this exact Teaching Name and posting. Attendance submissions will be preserved and will display the updated event duration.</p>
            <p>A longer mapped duration may create or expand schedule overlaps. Mapping remains authoritative: overlapping events and existing attendance are preserved, and residents must submit only the session they attended.</p>
          </div>
        ) : null}
      </DetailDrawer>

      <DetailDrawer
        title="Confirm atomic bulk mapping"
        open={interaction.overlay === 'bulk-confirmation' && bulkConfirmation !== null}
        onClose={() => closeActiveOverlay('bulk-confirmation')}
        closeDisabled={interactionPending}
        busy={bulkMutationPending}
        footer={
          <>
            <button type="button" className="button button-ghost" onClick={() => closeActiveOverlay('bulk-confirmation')} disabled={interactionPending}>Cancel</button>
            <button
              type="button"
              className="button button-primary"
              onClick={() => {
                const confirmation = bulkConfirmation
                if (confirmation && beginInteractionWithinOverlay('bulk-confirmation', 'bulk-mutation')) {
                  void executeBulkMappings(confirmation.items, true)
                }
              }}
              disabled={interactionPending}
            >
              Confirm atomic bulk change
            </button>
          </>
        }
      >
        {bulkConfirmation ? (
          <div className="pc-session-types-confirmation" role="status">
            <p>The {bulkConfirmation.items.length} prepared change{bulkConfirmation.items.length === 1 ? '' : 's'} may affect {impactSummary(bulkConfirmation.impact)}. Only aggregate counts are shown.</p>
            <p>All rows are applied together or none are applied. Existing event durations and end times will be recalculated for the affected exact scopes. Attendance submissions will be preserved and will display the updated event duration.</p>
            <p>Longer mapped durations may create or expand schedule overlaps. Mapping remains authoritative: overlapping events and existing attendance are preserved, and residents must submit only the session they attended.</p>
          </div>
        ) : null}
      </DetailDrawer>
    </div>
  )
}
