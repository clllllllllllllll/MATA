import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import {
  createSecretaryTeachingName,
  deactivateSecretaryTeachingName,
  deleteSecretaryTeachingName,
  listSecretaryTeachingNameProgrammes,
  listSecretaryTeachingNames,
  notifySecretaryTeachingNamesChanged,
  reactivateSecretaryTeachingName,
  renameSecretaryTeachingName,
  type SecretaryTeachingName,
} from '../../api/secretaryTeachingNames'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconPlus, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { useAppState } from '../../context/useAppState'
import {
  formatReportingPeriodOptionLabel,
  isEffectivelyActiveReportingPeriod,
} from '../../utils/reportingPeriods'
import {
  resolveTeachingNameLifecycleError,
} from '../../utils/secretaryTeachingNameState'
import { createScopedRequestFence } from '../../utils/scopedRequestFence'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'

type LifecycleFilter = 'active' | 'inactive' | 'all'
type DrawerMode = 'create' | 'edit'
type FeedbackTone = 'success' | 'warning'

const PAGE_SIZE = 50

const filterValue = (filter: LifecycleFilter): boolean | undefined => {
  if (filter === 'active') {
    return true
  }
  if (filter === 'inactive') {
    return false
  }
  return undefined
}

const sourceLabel = (name: SecretaryTeachingName): string =>
  name.visibilityScope === 'programme_private'
    ? 'PC \u00b7 NHG'
    : `Department Secretary${name.originPostingCode ? ` \u00b7 ${name.originPostingCode}` : ''}`

export const SecretaryTeachingNamesPage = () => {
  const {
    reportingPeriodId,
    setReportingPeriodId,
    reportingPeriods,
    reportingPeriodsLoading,
    reportingPeriodsError,
  } = useAppState()

  const [programmes, setProgrammes] = useState<string[]>([])
  const [programmesLoading, setProgrammesLoading] = useState(true)
  const [programmesLoaded, setProgrammesLoaded] = useState(false)
  const [programmesError, setProgrammesError] = useState<string | null>(null)
  const [selectedProgrammeCode, setSelectedProgrammeCode] = useState('')
  const programmeRequestRef = useRef(0)

  const [filter, setFilter] = useState<LifecycleFilter>('active')
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [names, setNames] = useState<SecretaryTeachingName[]>([])
  const [total, setTotal] = useState(0)
  const [namesLoading, setNamesLoading] = useState(false)
  const [namesError, setNamesError] = useState<string | null>(null)
  const namesRequestFenceRef = useRef(createScopedRequestFence())

  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerMode, setDrawerMode] = useState<DrawerMode>('create')
  const [editingName, setEditingName] = useState<SecretaryTeachingName | null>(null)
  const [formTeachingName, setFormTeachingName] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [drawerSaving, setDrawerSaving] = useState(false)

  const [mutatingNameId, setMutatingNameId] = useState<string | null>(null)
  const [feedback, setFeedback] = useState<string | null>(null)
  const [feedbackTone, setFeedbackTone] = useState<FeedbackTone>('success')
  const [feedbackNeedsRefresh, setFeedbackNeedsRefresh] = useState(false)

  const selectedPeriod = useMemo(() => {
    const candidate = reportingPeriods.find((period) => period.id === reportingPeriodId)
    return candidate && isEffectivelyActiveReportingPeriod(candidate) ? candidate : undefined
  }, [reportingPeriodId, reportingPeriods])
  const selectedPeriodId = selectedPeriod?.id ?? ''
  const selectedScopeKey = selectedProgrammeCode && selectedPeriodId
    ? `${selectedProgrammeCode}:${selectedPeriodId}`
    : null
  const selectedScopeRef = useRef<string | null>(selectedScopeKey)
  const listScopeKey = selectedProgrammeCode && selectedPeriodId
    ? `${selectedProgrammeCode}:${selectedPeriodId}:${filter}:${search}:${offset}`
    : null
  const listScopeRef = useRef<string | null>(listScopeKey)

  useEffect(() => {
    selectedScopeRef.current = selectedScopeKey
  }, [selectedScopeKey])

  useEffect(() => {
    listScopeRef.current = listScopeKey
  }, [listScopeKey])

  const loadProgrammes = useCallback(async () => {
    const requestId = programmeRequestRef.current + 1
    programmeRequestRef.current = requestId
    setProgrammesLoading(true)
    setProgrammesError(null)
    try {
      const response = await listSecretaryTeachingNameProgrammes()
      if (programmeRequestRef.current !== requestId) {
        return
      }
      const nextProgrammes = [...new Set(response.map((item) => item.programmeCode))]
      setProgrammes(nextProgrammes)
      setSelectedProgrammeCode((current) =>
        current && nextProgrammes.includes(current) ? current : nextProgrammes[0] ?? '',
      )
      setProgrammesLoaded(true)
    } catch (error) {
      if (programmeRequestRef.current !== requestId) {
        return
      }
      setProgrammes([])
      setSelectedProgrammeCode('')
      setProgrammesLoaded(false)
      setProgrammesError(formatUserFacingApiError(error, {
        fallbackMessage: 'Teaching Name access could not be loaded. Try refreshing the page.',
      }))
    } finally {
      if (programmeRequestRef.current === requestId) {
        setProgrammesLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    let active = true
    void Promise.resolve().then(() => {
      if (active) {
        return loadProgrammes()
      }
      return undefined
    })
    return () => {
      active = false
      programmeRequestRef.current += 1
    }
  }, [loadProgrammes])

  useEffect(() => {
    let active = true
    void Promise.resolve().then(() => {
      if (!active) {
        return
      }
      setNames([])
      setTotal(0)
      setNamesError(null)
      setOffset(0)
      setDrawerOpen(false)
      setEditingName(null)
      setFormError(null)
      setDrawerSaving(false)
      setMutatingNameId(null)
      namesRequestFenceRef.current.invalidate()
      setFeedback(null)
      setFeedbackNeedsRefresh(false)
    })
    return () => {
      active = false
    }
  }, [selectedProgrammeCode, selectedPeriodId])

  const loadNames = useCallback(async () => {
    const requestedScopeKey = listScopeKey
    const requestToken = namesRequestFenceRef.current.begin(requestedScopeKey)
    if (!requestedScopeKey || !selectedProgrammeCode || !selectedPeriodId) {
      setNames([])
      setTotal(0)
      setNamesError(null)
      setNamesLoading(false)
      return
    }

    setNamesLoading(true)
    setNamesError(null)
    try {
      const response = await listSecretaryTeachingNames({
        reportingPeriodId: selectedPeriodId,
        programmeCode: selectedProgrammeCode,
        isActive: filterValue(filter),
        search,
        limit: PAGE_SIZE,
        offset,
      })
      if (!namesRequestFenceRef.current.isCurrent(requestToken, listScopeRef.current)) {
        return
      }
      setNames(response.items)
      setTotal(response.total)
    } catch (error) {
      if (!namesRequestFenceRef.current.isCurrent(requestToken, listScopeRef.current)) {
        return
      }
      setNames([])
      setTotal(0)
      setNamesError(formatUserFacingApiError(error, {
        fallbackMessage: 'Teaching Names could not be loaded. Try refreshing the list.',
      }))
    } finally {
      if (namesRequestFenceRef.current.isCurrent(requestToken, listScopeRef.current)) {
        setNamesLoading(false)
      }
    }
  }, [filter, listScopeKey, offset, search, selectedPeriodId, selectedProgrammeCode])

  useEffect(() => {
    let active = true
    void Promise.resolve().then(() => {
      if (active) {
        return loadNames()
      }
      return undefined
    })
    return () => {
      active = false
    }
  }, [loadNames])

  const clearFeedback = () => {
    setFeedback(null)
    setFeedbackNeedsRefresh(false)
  }

  const openCreateDrawer = () => {
    if (!selectedProgrammeCode || !selectedPeriod) {
      setFeedbackTone('warning')
      setFeedback('Select an authorised programme and active reporting period before updating Teaching Names.')
      return
    }
    clearFeedback()
    setDrawerMode('create')
    setEditingName(null)
    setFormTeachingName('')
    setFormError(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (name: SecretaryTeachingName) => {
    if (!name.canManageName) {
      setFeedbackTone('warning')
      setFeedback('This PC · NHG name is visible for scheduling but its lifecycle is managed by the Programme PC.')
      return
    }
    clearFeedback()
    setDrawerMode('edit')
    setEditingName(name)
    setFormTeachingName(name.teachingName)
    setFormError(null)
    setDrawerOpen(true)
  }

  const closeDrawer = () => {
    if (drawerSaving) {
      return
    }
    setDrawerOpen(false)
    setEditingName(null)
    setFormError(null)
  }

  const submitNameForm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const teachingName = formTeachingName.trim()
    if (!teachingName) {
      setFormError('Name of Teaching is required.')
      return
    }
    if (!selectedProgrammeCode || !selectedPeriodId) {
      setFormError('The selected programme or reporting period is no longer available.')
      return
    }

    setDrawerSaving(true)
    setFormError(null)
    const requestedScopeKey = selectedScopeRef.current
    try {
      if (drawerMode === 'edit') {
        if (!editingName) {
          setFormError('Select a Teaching Name to update first.')
          return
        }
        await renameSecretaryTeachingName({
          teachingNameId: editingName.id,
          teachingName,
          expectedRevision: editingName.revision,
        })
      } else {
        await createSecretaryTeachingName({
          reportingPeriodId: selectedPeriodId,
          programmeCode: selectedProgrammeCode,
          teachingName,
        })
      }
      notifySecretaryTeachingNamesChanged()
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      setDrawerOpen(false)
      setEditingName(null)
      setFeedbackTone('success')
      setFeedback(drawerMode === 'edit' ? 'Name of Teaching updated.' : 'Name of Teaching created.')
      setFeedbackNeedsRefresh(false)
      await loadNames()
    } catch (error) {
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      const result = resolveTeachingNameLifecycleError(
        error,
        drawerMode === 'edit'
          ? 'Name of Teaching could not be updated. Try again.'
          : 'Name of Teaching could not be created. Try again.',
      )
      setFormError(result.message)
      setFeedbackNeedsRefresh(result.needsRefresh)
    } finally {
      if (selectedScopeRef.current === requestedScopeKey) {
        setDrawerSaving(false)
      }
    }
  }

  const runLifecycleAction = async (
    name: SecretaryTeachingName,
    action: 'deactivate' | 'reactivate' | 'delete',
  ) => {
    if (!name.canManageName) {
      setFeedbackTone('warning')
      setFeedback('This PC · NHG name is read-only for the Department Secretary.')
      return
    }
    clearFeedback()
    setMutatingNameId(name.id)
    const requestedScopeKey = selectedScopeRef.current
    try {
      if (action === 'deactivate') {
        await deactivateSecretaryTeachingName({
          teachingNameId: name.id,
          expectedRevision: name.revision,
        })
      } else if (action === 'reactivate') {
        await reactivateSecretaryTeachingName({
          teachingNameId: name.id,
          expectedRevision: name.revision,
        })
      } else {
        await deleteSecretaryTeachingName({
          teachingNameId: name.id,
          expectedRevision: name.revision,
        })
      }
      notifySecretaryTeachingNamesChanged()
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      setFeedbackTone('success')
      setFeedback(
        action === 'deactivate'
          ? 'Name of Teaching deactivated.'
          : action === 'reactivate'
            ? 'Name of Teaching reactivated.'
            : 'Name of Teaching deleted.',
      )
      setFeedbackNeedsRefresh(false)
      await loadNames()
    } catch (error) {
      if (selectedScopeRef.current !== requestedScopeKey) {
        return
      }
      const result = resolveTeachingNameLifecycleError(error, 'Name of Teaching could not be updated. Try again.')
      setFeedbackTone('warning')
      setFeedback(result.message)
      setFeedbackNeedsRefresh(result.needsRefresh)
    } finally {
      if (selectedScopeRef.current === requestedScopeKey) {
        setMutatingNameId(null)
      }
    }
  }

  const hasNoCapability = programmesLoaded && programmes.length === 0
  const canManageNames = Boolean(selectedProgrammeCode && selectedPeriod && !programmesError)
  const isSingleProgramme = programmes.length === 1
  const currentPage = Math.floor(offset / PAGE_SIZE) + 1
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="page secretary-teaching-names-page">
      <PageHero
        title="Names of Teaching"
        subtitle="Manage approved Teaching Names in your authorised programme pool."
        actions={
          <button
            type="button"
            className="button button-primary"
            onClick={openCreateDrawer}
            disabled={!canManageNames}
            title={canManageNames ? 'Create a Name of Teaching.' : 'Select an authorised programme and active reporting period first.'}
          >
            <IconPlus size={15} />
            Add Name of Teaching
          </button>
        }
      />

      <section className="card secretary-teaching-names-scope-card" aria-label="Teaching Name scope">
        {programmesError ? (
          <div className="inline-callout callout-error" role="alert">
            <span>{programmesError}</span>
            <button type="button" className="button button-ghost" onClick={() => void loadProgrammes()}>
              <IconRefresh size={14} />
              Retry
            </button>
          </div>
        ) : null}

        {hasNoCapability ? (
          <div className="secretary-teaching-names-empty-state" role="status">
            <h3>No Teaching Name access</h3>
            <p>You do not currently have an active programme capability for Teaching Name management.</p>
          </div>
        ) : (
          <div className="secretary-teaching-names-scope-controls">
            {programmesLoading ? <span className="inline-muted">Loading authorised programmes...</span> : null}
            {isSingleProgramme ? (
              <p className="secretary-teaching-names-scope-copy">
                Teaching Name access is limited to your authorised programme scope: <strong>{programmes[0]}</strong>
              </p>
            ) : programmes.length > 1 ? (
              <label className="secretary-teaching-names-select">
                <span>Authorised programme scope</span>
                <select
                  value={selectedProgrammeCode}
                  onChange={(event) => setSelectedProgrammeCode(event.target.value)}
                  aria-label="Programme"
                >
                  {programmes.map((programmeCode) => (
                    <option key={programmeCode} value={programmeCode}>{programmeCode}</option>
                  ))}
                </select>
              </label>
            ) : null}

            <label className="secretary-teaching-names-select">
              <span>Reporting period</span>
              {reportingPeriodsLoading ? <span className="inline-muted">Loading reporting periods...</span> : null}
              {!reportingPeriodsLoading && reportingPeriods.length > 0 ? (
                <select
                  value={selectedPeriodId}
                  onChange={(event) => setReportingPeriodId(event.target.value)}
                  aria-label="Reporting period"
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
              ) : null}
              {reportingPeriodsError ? <span className="upload-validation-text">{reportingPeriodsError}</span> : null}
              {!reportingPeriodsLoading && !reportingPeriodsError && !selectedPeriod ? (
                <span className="upload-validation-text">Select an active reporting period.</span>
              ) : null}
            </label>
          </div>
        )}
      </section>

      {!programmesLoading && !programmesError && !hasNoCapability ? (
        <section className="card secretary-teaching-names-list-card" aria-label="Teaching Names">
          <div className="section-header secretary-teaching-names-list-header">
            <div>
              <h2>Names of Teaching</h2>
              <p>Only names in the selected programme and reporting period are shown.</p>
            </div>
            <button type="button" className="button button-secondary" onClick={() => void loadNames()} disabled={!canManageNames || namesLoading}>
              <IconRefresh size={14} />
              Refresh
            </button>
          </div>

          <form
            className="secretary-teaching-names-filters"
            onSubmit={(event) => {
              event.preventDefault()
              setOffset(0)
              setSearch(searchInput)
            }}
          >
            <div className="filter-row" aria-label="Teaching Name status">
              {(['active', 'inactive', 'all'] as const).map((value) => (
                <button
                  key={value}
                  type="button"
                  className={`filter-chip ${filter === value ? 'active' : ''}`}
                  onClick={() => {
                    setFilter(value)
                    setOffset(0)
                  }}
                >
                  {value[0].toUpperCase() + value.slice(1)}
                </button>
              ))}
            </div>
            <label className="secretary-teaching-names-search">
              <span className="sr-only">Search Names of Teaching</span>
              <input
                type="search"
                value={searchInput}
                onChange={(event) => setSearchInput(event.target.value)}
                placeholder="Search Names of Teaching"
                aria-label="Search Names of Teaching"
              />
            </label>
            <button type="submit" className="button button-secondary">Search</button>
          </form>

          {feedback ? (
            <div className={`inline-callout ${feedbackTone === 'success' ? 'callout-success' : 'callout-warning'} secretary-teaching-names-feedback`} role={feedbackTone === 'warning' ? 'alert' : 'status'}>
              <span>{feedback}</span>
              {feedbackNeedsRefresh ? (
                <button type="button" className="button button-ghost" onClick={() => void loadNames()}>
                  <IconRefresh size={14} />
                  Refresh list
                </button>
              ) : null}
            </div>
          ) : null}
          {namesError ? (
            <div className="inline-callout callout-error secretary-teaching-names-feedback" role="alert">
              <span>{namesError}</span>
              <button type="button" className="button button-ghost" onClick={() => void loadNames()}>
                <IconRefresh size={14} />
                Retry
              </button>
            </div>
          ) : null}

          <div className="table-wrap secretary-teaching-names-table-wrap">
            <div className="table-scroll">
              <table className="table">
                <colgroup>
                  <col className="secretary-teaching-names-col-name" />
                  <col className="secretary-teaching-names-col-programme" />
                  <col className="secretary-teaching-names-col-period" />
                  <col className="secretary-teaching-names-col-state" />
                  <col className="secretary-teaching-names-col-actions" />
                </colgroup>
                <thead>
                  <tr>
                    <th>Name of Teaching</th>
                    <th>Programme</th>
                    <th>Reporting period</th>
                    <th>State</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {namesLoading ? (
                    <tr><td colSpan={5}>Loading Names of Teaching...</td></tr>
                  ) : names.length === 0 ? (
                    <tr><td colSpan={5}>No Names of Teaching match this scope.</td></tr>
                  ) : names.map((name) => {
                    const isMutating = mutatingNameId === name.id
                    return (
                      <tr key={name.id}>
                        <td className="secretary-teaching-name safe-wrap">
                          <strong>{name.teachingName}</strong>
                          <div className="inline-muted">{sourceLabel(name)}</div>
                        </td>
                        <td className="mono">{name.programmeCode}</td>
                        <td>{selectedPeriod?.label ?? name.reportingPeriodId}</td>
                        <td>
                          <span className={`status-badge ${name.isActive ? 'status-badge-success' : 'status-badge-neutral'}`}>
                            {name.isActive ? 'Active' : 'Inactive'}
                          </span>
                        </td>
                        <td>
                          <div className="secretary-teaching-names-actions">
                            <button type="button" className="button button-ghost" onClick={() => openEditDrawer(name)} disabled={isMutating || !name.canManageName}>Rename</button>
                            <button
                              type="button"
                              className="button button-ghost"
                              onClick={() => void runLifecycleAction(name, name.isActive ? 'deactivate' : 'reactivate')}
                              disabled={isMutating || !name.canManageName}
                            >
                              {name.isActive ? 'Deactivate' : 'Reactivate'}
                            </button>
                            <button
                              type="button"
                              className="button button-ghost danger"
                              onClick={() => void runLifecycleAction(name, 'delete')}
                              disabled={isMutating || !name.canManageName}
                            >
                              Delete
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="secretary-teaching-names-mobile-list" aria-label="Teaching Name cards">
            {namesLoading ? <div className="mobile-record-card">Loading Names of Teaching...</div> : null}
            {!namesLoading && names.length === 0 ? <div className="mobile-record-card">No Names of Teaching match this scope.</div> : null}
            {!namesLoading ? names.map((name) => {
              const isMutating = mutatingNameId === name.id
              return (
                <article key={name.id} className="mobile-record-card secretary-teaching-names-mobile-card">
                  <div className="secretary-teaching-names-mobile-heading">
                    <strong className="safe-wrap">{name.teachingName}</strong>
                    <span className={`status-badge ${name.isActive ? 'status-badge-success' : 'status-badge-neutral'}`}>
                      {name.isActive ? 'Active' : 'Inactive'}
                    </span>
                  </div>
                  <p>{sourceLabel(name)}</p>
                  <p>{name.programmeCode} · {selectedPeriod?.label ?? name.reportingPeriodId}</p>
                  <div className="secretary-teaching-names-mobile-actions">
                    <button type="button" className="button button-secondary" onClick={() => openEditDrawer(name)} disabled={isMutating || !name.canManageName}>Rename</button>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => void runLifecycleAction(name, name.isActive ? 'deactivate' : 'reactivate')}
                      disabled={isMutating || !name.canManageName}
                    >
                      {name.isActive ? 'Deactivate' : 'Reactivate'}
                    </button>
                    <button
                      type="button"
                      className="button button-ghost danger"
                      onClick={() => void runLifecycleAction(name, 'delete')}
                      disabled={isMutating || !name.canManageName}
                    >
                      Delete
                    </button>
                  </div>
                </article>
              )
            }) : null}
          </div>

          {total > PAGE_SIZE ? (
            <div className="secretary-teaching-names-pagination" aria-label="Teaching Name pagination">
              <span>Page {currentPage} of {pageCount}</span>
              <button type="button" className="button button-secondary" disabled={offset === 0 || namesLoading} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>Previous</button>
              <button type="button" className="button button-secondary" disabled={offset + PAGE_SIZE >= total || namesLoading} onClick={() => setOffset(offset + PAGE_SIZE)}>Next</button>
            </div>
          ) : null}
        </section>
      ) : null}

      <DetailDrawer
        title="Update Name of Teaching"
        open={drawerOpen}
        onClose={closeDrawer}
        closeDisabled={drawerSaving}
        busy={drawerSaving}
        footer={
          <>
            <button type="button" className="button button-ghost" onClick={closeDrawer} disabled={drawerSaving}>Cancel</button>
            <button type="submit" className="button button-primary" form="secretary-teaching-name-form" disabled={drawerSaving}>
              {drawerSaving ? 'Saving' : drawerMode === 'edit' ? 'Save changes' : 'Create Name of Teaching'}
            </button>
          </>
        }
      >
        <form id="secretary-teaching-name-form" className="secretary-form-grid" onSubmit={(event) => void submitNameForm(event)}>
          <div className="secretary-teaching-names-form-context" aria-label="Selected scope">
            <span>Programme: {selectedProgrammeCode}</span>
            <span>Reporting period: {selectedPeriod?.label ?? '-'}</span>
          </div>
          <label>
            Name of Teaching
            <input
              value={formTeachingName}
              onChange={(event) => setFormTeachingName(event.target.value)}
              autoFocus
              maxLength={200}
              disabled={drawerSaving}
            />
          </label>
          {formError ? <div className="inline-callout callout-error" role="alert">{formError}</div> : null}
        </form>
      </DetailDrawer>
    </div>
  )
}
