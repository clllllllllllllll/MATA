import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from 'react'
import { Link } from 'react-router-dom'
import {
  listPcResidentAttendance,
  type PcResidentAttendanceOverviewFilters,
  type PcResidentAttendanceOverviewItem,
} from '../../api/pcResidentAttendance'
import { IconChevRight, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { useAuth } from '../../context/useAuth'
import { useAppState } from '../../context/useAppState'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'
import {
  displayCurrentPosting,
  pageRangeLabel,
  pcResidentAttendanceDetailPath,
} from './pcResidentAttendancePageLogic'

const pageSize = 25

interface OverviewFilterState {
  search: string
  programmeCode: string
  postingCode: string
}

const emptyFilters: OverviewFilterState = {
  search: '',
  programmeCode: '',
  postingCode: '',
}

export const PcResidentAttendancePage = () => {
  const { identity } = useAuth()
  const { demoAdminId, reportingPeriodAuthenticationContextVersion } = useAppState()
  const [residents, setResidents] = useState<PcResidentAttendanceOverviewItem[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [draftFilters, setDraftFilters] = useState<OverviewFilterState>(emptyFilters)
  const [appliedFilters, setAppliedFilters] = useState<OverviewFilterState>(emptyFilters)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [loadedAuthenticationContextKey, setLoadedAuthenticationContextKey] = useState('')
  const requestVersionRef = useRef(0)

  const pcAdminId = identity?.role === 'programme_pc' ? identity.subjectId : demoAdminId
  const programmeScope = useMemo(
    () => identity?.role === 'programme_pc'
      ? [...new Set(identity.programmeScope.map((code) => code.trim()).filter(Boolean))]
      : [],
    [identity],
  )
  const authenticationContextKey = useMemo(
    () => JSON.stringify([
      reportingPeriodAuthenticationContextVersion,
      identity?.role ?? null,
      identity?.subjectId ?? null,
      programmeScope,
    ]),
    [identity, programmeScope, reportingPeriodAuthenticationContextVersion],
  )
  const authenticationContextKeyRef = useRef(authenticationContextKey)
  useLayoutEffect(() => {
    authenticationContextKeyRef.current = authenticationContextKey
  }, [authenticationContextKey])
  const previousAuthenticationContextKeyRef = useRef(authenticationContextKey)
  const [filtersAuthenticationContextKey, setFiltersAuthenticationContextKey] = useState(
    authenticationContextKey,
  )
  const filtersMatchAuthenticationContext =
    filtersAuthenticationContextKey === authenticationContextKey
  const visibleDraftFilters = filtersMatchAuthenticationContext ? draftFilters : emptyFilters
  const effectiveAppliedFilters = filtersMatchAuthenticationContext ? appliedFilters : emptyFilters
  const contextMatchesLoadedData = loadedAuthenticationContextKey === authenticationContextKey
  const visibleResidents = contextMatchesLoadedData ? residents : []
  const visibleTotal = contextMatchesLoadedData ? total : 0
  const visibleLoading = loading || !contextMatchesLoadedData

  useEffect(() => {
    if (previousAuthenticationContextKeyRef.current === authenticationContextKey) {
      return
    }
    previousAuthenticationContextKeyRef.current = authenticationContextKey
    requestVersionRef.current += 1
    setLoadedAuthenticationContextKey('')
    setFiltersAuthenticationContextKey(authenticationContextKey)
    setResidents([])
    setTotal(0)
    setOffset(0)
    setDraftFilters(emptyFilters)
    setAppliedFilters(emptyFilters)
    setError(null)
    setLoading(true)
  }, [authenticationContextKey])

  const loadResidents = useCallback(async () => {
    const requestVersion = requestVersionRef.current + 1
    requestVersionRef.current = requestVersion

    if (programmeScope.length === 0) {
      setResidents([])
      setTotal(0)
      setLoadedAuthenticationContextKey(authenticationContextKey)
      setLoading(false)
      setError('No programme scope is available for this account.')
      return
    }

    setLoading(true)
    setError(null)
    const filters: PcResidentAttendanceOverviewFilters = {
      programmeCode: effectiveAppliedFilters.programmeCode || undefined,
      search: effectiveAppliedFilters.search || undefined,
      postingCode: effectiveAppliedFilters.postingCode || undefined,
      limit: pageSize,
      offset,
    }

    try {
      const response = await listPcResidentAttendance(
        { adminId: pcAdminId, programmeScope },
        filters,
      )
      if (
        requestVersion !== requestVersionRef.current
        || authenticationContextKey !== authenticationContextKeyRef.current
      ) {
        return
      }
      setResidents(response.items)
      setTotal(response.total)
      setLoadedAuthenticationContextKey(authenticationContextKey)
    } catch (loadError) {
      if (
        requestVersion !== requestVersionRef.current
        || authenticationContextKey !== authenticationContextKeyRef.current
      ) {
        return
      }
      setResidents([])
      setTotal(0)
      setLoadedAuthenticationContextKey(authenticationContextKey)
      setError(formatUserFacingApiError(loadError, {
        fallbackMessage: 'Unable to load NHG resident attendance.',
        authMessage: 'NHG resident attendance is not available for this account.',
      }))
    } finally {
      if (
        requestVersion === requestVersionRef.current
        && authenticationContextKey === authenticationContextKeyRef.current
      ) {
        setLoading(false)
      }
    }
  }, [
    authenticationContextKey,
    effectiveAppliedFilters,
    offset,
    pcAdminId,
    programmeScope,
  ])

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadResidents()
    }, 0)
    return () => window.clearTimeout(timer)
  }, [loadResidents])

  const applyFilters = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setOffset(0)
    setAppliedFilters({
      search: visibleDraftFilters.search.trim(),
      programmeCode: visibleDraftFilters.programmeCode,
      postingCode: visibleDraftFilters.postingCode.trim(),
    })
  }

  const clearFilters = () => {
    setDraftFilters(emptyFilters)
    setAppliedFilters(emptyFilters)
    setOffset(0)
  }

  const canGoPrevious = offset > 0
  const canGoNext = offset + pageSize < visibleTotal
  const rangeLabel = pageRangeLabel(visibleTotal, offset, visibleResidents.length)
  const hasAppliedFilters = Boolean(
    effectiveAppliedFilters.search
    || effectiveAppliedFilters.programmeCode
    || effectiveAppliedFilters.postingCode,
  )

  return (
    <div className="page pc-attendance-page pc-resident-attendance-page">
      <PageHero
        title="NHG Resident Attendance"
        subtitle="Programme PC - read-only attendance history for residents in your assigned programmes"
        actions={
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void loadResidents()}
            disabled={visibleLoading}
          >
            <IconRefresh size={14} />
            Refresh
          </button>
        }
      />

      <form className="card filter-bar pc-attendance-filter-card pc-resident-attendance-filters" onSubmit={applyFilters}>
        <label>
          Resident name or MCR
          <input
            type="search"
            value={visibleDraftFilters.search}
            onChange={(event) => setDraftFilters((current) => ({
              ...current,
              search: event.target.value,
            }))}
            placeholder="Search resident"
            disabled={!filtersMatchAuthenticationContext}
          />
        </label>
        <label>
          Programme
          {programmeScope.length > 1 ? (
            <select
              value={visibleDraftFilters.programmeCode}
              onChange={(event) => setDraftFilters((current) => ({
                ...current,
                programmeCode: event.target.value,
              }))}
              disabled={!filtersMatchAuthenticationContext}
            >
              <option value="">All assigned programmes</option>
              {programmeScope.map((programmeCode) => (
                <option key={programmeCode} value={programmeCode}>{programmeCode}</option>
              ))}
            </select>
          ) : (
            <input
              value={filtersMatchAuthenticationContext ? programmeScope[0] ?? 'No programme scope' : ''}
              readOnly
              disabled={!filtersMatchAuthenticationContext}
            />
          )}
        </label>
        <label>
          Current posting
          <input
            value={visibleDraftFilters.postingCode}
            onChange={(event) => setDraftFilters((current) => ({
              ...current,
              postingCode: event.target.value,
            }))}
            placeholder="Posting code"
            disabled={!filtersMatchAuthenticationContext}
          />
        </label>
        <div className="pc-resident-attendance-filter-actions">
          <button
            type="submit"
            className="button button-primary"
            disabled={!filtersMatchAuthenticationContext}
          >
            Apply filters
          </button>
          <button
            type="button"
            className="button button-secondary"
            onClick={clearFilters}
            disabled={
              !filtersMatchAuthenticationContext
              || (
                !hasAppliedFilters
                && !visibleDraftFilters.search
                && !visibleDraftFilters.programmeCode
                && !visibleDraftFilters.postingCode
              )
            }
          >
            Clear filters
          </button>
        </div>
      </form>

      {visibleLoading && visibleResidents.length === 0 ? (
        <section className="card warning-state-card" aria-live="polite">
          Loading NHG residents...
        </section>
      ) : null}

      {!visibleLoading && error ? (
        <section className="card warning-state-card" role="alert">
          <strong>NHG resident attendance could not be loaded.</strong>
          <p>{error}</p>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void loadResidents()}
          >
            Retry
          </button>
        </section>
      ) : null}

      {!visibleLoading && !error && visibleResidents.length === 0 ? (
        <section className="card warning-state-card">
          <strong>No NHG residents found for the selected filters.</strong>
        </section>
      ) : null}

      {!error && visibleResidents.length > 0 ? (
        <section className={`card pc-attendance-table-card pc-resident-attendance-table-card ${visibleLoading ? 'is-refetching' : ''}`}>
          <div className="section-header pc-attendance-list-header pc-resident-attendance-list-header">
            <div>
              <h2>NHG Residents</h2>
              <p>Attendance submissions are native NHG records only.</p>
            </div>
            <span className="inline-muted">{rangeLabel}</span>
          </div>

          <div className="table-scroll">
            <table className="table pc-resident-attendance-overview-table">
              <thead>
                <tr>
                  <th>Resident name</th>
                  <th>MCR</th>
                  <th>Programme</th>
                  <th>R year</th>
                  <th>Current posting</th>
                  <th>Total attendance submissions</th>
                  <th className="pc-resident-attendance-action-header">Action</th>
                </tr>
              </thead>
              <tbody>
                {visibleResidents.map((resident) => (
                  <tr key={resident.residentId}>
                    <td><strong>{resident.name}</strong></td>
                    <td className="mono">{resident.mcr}</td>
                    <td>{resident.programmeCode}</td>
                    <td>{resident.rYear ?? '-'}</td>
                    <td>{displayCurrentPosting(resident)}</td>
                    <td className="mono">{resident.attendanceCount}</td>
                    <td className="pc-resident-attendance-action-cell">
                      <Link
                        className="button button-secondary pc-resident-attendance-view-link"
                        to={pcResidentAttendanceDetailPath(resident.residentId)}
                      >
                        View attendance
                        <IconChevRight size={14} />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div
            className="responsive-card-list pc-attendance-mobile-list pc-resident-attendance-mobile-list"
            aria-label="NHG resident attendance cards"
          >
            {visibleResidents.map((resident) => (
              <article className="mobile-record-card pc-attendance-record-card pc-resident-attendance-card" key={resident.residentId}>
                <div className="pc-attendance-card-header pc-resident-attendance-card-header">
                  <strong className="safe-wrap">{resident.name}</strong>
                  <span className="mono">{resident.mcr}</span>
                </div>
                <dl className="pc-attendance-card-details pc-resident-attendance-card-details">
                  <div><dt>Programme</dt><dd>{resident.programmeCode}</dd></div>
                  <div><dt>R year</dt><dd>{resident.rYear ?? '-'}</dd></div>
                  <div><dt>Current posting</dt><dd>{displayCurrentPosting(resident)}</dd></div>
                  <div><dt>Submissions</dt><dd>{resident.attendanceCount}</dd></div>
                </dl>
                <Link
                  className="button button-secondary pc-resident-attendance-view-link"
                  to={pcResidentAttendanceDetailPath(resident.residentId)}
                >
                  View attendance
                  <IconChevRight size={14} />
                </Link>
              </article>
            ))}
          </div>

          <div className="upload-log-pagination pc-resident-attendance-pagination">
            <span>{rangeLabel}</span>
            <div>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setOffset(Math.max(0, offset - pageSize))}
                disabled={!canGoPrevious || visibleLoading}
              >
                Previous
              </button>
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setOffset(offset + pageSize)}
                disabled={!canGoNext || visibleLoading}
              >
                Next
              </button>
            </div>
          </div>
        </section>
      ) : null}
    </div>
  )
}
