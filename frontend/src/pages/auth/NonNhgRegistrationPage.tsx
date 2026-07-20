import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  listNonNhgRegistrationOptions,
  registerNonNhgResident,
  type NonNhgRegistrationAvailability,
  type NonNhgRegistrationOptions,
  type NonNhgRegistrationResult,
} from '../../api/auth'
import { ApiRequestError } from '../../api/http'
import { IconCheck, IconChevRight } from '../../components/icons'
import { defaultPathForRole } from '../../config/navigation'
import { useAuth } from '../../context/useAuth'

type HomeCluster = 'NUH' | 'SingHealth'

interface PostingScheduleRowState {
  id: string
  startDate: string
  endDate: string
  programmeCode: string
  institution: string
}

interface RegistrationFormState {
  name: string
  mcr: string
  homeCluster: HomeCluster | ''
  postingSchedule: PostingScheduleRowState[]
}

const createScheduleRow = (id: string): PostingScheduleRowState => ({
  id,
  startDate: '',
  endDate: '',
  programmeCode: '',
  institution: '',
})

const INITIAL_FORM: RegistrationFormState = {
  name: '',
  mcr: '',
  homeCluster: '',
  postingSchedule: [createScheduleRow('posting-1')],
}

const REGISTER_ERROR = 'Unable to register. Check your details and try again.'
const REGISTRATION_RATE_LIMIT_ERROR = 'Too many registration attempts. Please try again later.'
const REGISTRATION_OPTIONS_ERROR = 'Posting options are unavailable. Please try again later.'
const NO_CONFIGURED_INSTITUTIONS = 'No institutions are configured for registration.'
const PENDING_MAPPING_MESSAGE = 'Posting configuration for this programme is pending.'
const EMPTY_REGISTRATION_OPTIONS: NonNhgRegistrationOptions = {
  institutions: [],
  programmes: [],
}

export const NonNhgRegistrationPage = () => {
  const navigate = useNavigate()
  const { loginWithSession } = useAuth()
  const [form, setForm] = useState<RegistrationFormState>(INITIAL_FORM)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [registrationResult, setRegistrationResult] = useState<NonNhgRegistrationResult | null>(null)
  const [registrationOptions, setRegistrationOptions] = useState<NonNhgRegistrationOptions>(
    EMPTY_REGISTRATION_OPTIONS,
  )
  const [registrationOptionsLoading, setRegistrationOptionsLoading] = useState(true)
  const [registrationOptionsError, setRegistrationOptionsError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    const loadRegistrationOptions = async () => {
      try {
        const options = await listNonNhgRegistrationOptions()
        if (!active) return
        setRegistrationOptions(options)
        setRegistrationOptionsError(null)
      } catch {
        if (!active) return
        setRegistrationOptions(EMPTY_REGISTRATION_OPTIONS)
        setRegistrationOptionsError(REGISTRATION_OPTIONS_ERROR)
      } finally {
        if (active) setRegistrationOptionsLoading(false)
      }
    }
    void loadRegistrationOptions()
    return () => {
      active = false
    }
  }, [])

  const programmeInstitutionMappings = (
    programmeCode: string,
  ): NonNhgRegistrationAvailability[] =>
    registrationOptions.programmes.find((option) => option.programmeCode === programmeCode)
      ?.institutions ?? []

  const institutionName = (institutionCode: string): string =>
    registrationOptions.institutions.find(({ code }) => code === institutionCode)?.name ??
    institutionCode

  const isAvailableScheduleRow = (row: PostingScheduleRowState): boolean =>
    Boolean(row.institution) &&
    programmeInstitutionMappings(row.programmeCode).some(
      (mapping) =>
        mapping.institutionCode === row.institution && mapping.available,
    )

  const hasPendingMapping = (row: PostingScheduleRowState): boolean =>
    Boolean(row.programmeCode) &&
    programmeInstitutionMappings(row.programmeCode).some(
      (mapping) => mapping.status === 'pending' && !mapping.available,
    ) &&
    !isAvailableScheduleRow(row)

  const canSubmit =
    !registrationOptionsLoading &&
    !registrationOptionsError &&
    registrationOptions.institutions.length > 0 &&
    registrationOptions.programmes.length > 0 &&
    form.name.trim().length > 0 &&
    form.mcr.trim().length > 0 &&
    Boolean(form.homeCluster) &&
    form.postingSchedule.every((row) =>
      row.startDate &&
      row.endDate &&
      row.startDate <= row.endDate &&
      row.programmeCode &&
      isAvailableScheduleRow(row),
    )

  const updateForm = <Key extends keyof RegistrationFormState>(
    key: Key,
    value: RegistrationFormState[Key],
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }))
    setSubmitError(null)
  }

  const updateScheduleRow = <Key extends keyof PostingScheduleRowState>(
    rowId: string,
    key: Key,
    value: PostingScheduleRowState[Key],
  ) => {
    setForm((prev) => ({
      ...prev,
      postingSchedule: prev.postingSchedule.map((row) =>
        row.id === rowId ? { ...row, [key]: value } : row,
      ),
    }))
    setSubmitError(null)
  }

  const selectScheduleProgramme = (rowId: string, programmeCode: string) => {
    const firstAvailableInstitution = programmeInstitutionMappings(programmeCode).find(
      (mapping) => mapping.available,
    )?.institutionCode
    setForm((prev) => ({
      ...prev,
      postingSchedule: prev.postingSchedule.map((row) =>
        row.id === rowId
          ? {
              ...row,
              programmeCode,
              institution: firstAvailableInstitution ?? '',
            }
          : row,
      ),
    }))
    setSubmitError(null)
  }

  const addScheduleRow = () => {
    setForm((prev) => ({
      ...prev,
      postingSchedule: [
        ...prev.postingSchedule,
        createScheduleRow(`posting-${prev.postingSchedule.length + 1}-${Date.now()}`),
      ],
    }))
  }

  const removeScheduleRow = (rowId: string) => {
    setForm((prev) => ({
      ...prev,
      postingSchedule:
        prev.postingSchedule.length > 1
          ? prev.postingSchedule.filter((row) => row.id !== rowId)
          : prev.postingSchedule,
    }))
    setSubmitError(null)
  }

  const submitRegistration = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!canSubmit || !form.homeCluster) {
      setSubmitError(REGISTER_ERROR)
      setSubmitState('error')
      return
    }

    setSubmitState('submitting')
    setSubmitError(null)
    try {
      const result = await registerNonNhgResident({
        name: form.name,
        mcr: form.mcr,
        homeCluster: form.homeCluster,
        postingSchedule: form.postingSchedule.map((row) => ({
          startDate: row.startDate,
          endDate: row.endDate,
          programmeCode: row.programmeCode,
          institution: row.institution,
        })),
      })
      setRegistrationResult(result)
      setSubmitState('success')
    } catch (error) {
      let message = REGISTER_ERROR
      if (error instanceof ApiRequestError) {
        if (error.status === 429) {
          message = REGISTRATION_RATE_LIMIT_ERROR
        } else if (
          error.status === 422 &&
          (error.message.includes('Posting configuration') ||
            error.message.includes('No posting configuration'))
        ) {
          message = error.message
        }
      }
      setSubmitError(message)
      setSubmitState('error')
    }
  }

  const continueAfterSuccess = () => {
    if (registrationResult?.session) {
      loginWithSession(registrationResult.session)
      navigate(defaultPathForRole(registrationResult.session.identity.role), { replace: true })
      return
    }
    navigate('/login', { replace: true })
  }

  const postingResolutionError =
    submitError &&
    (submitError.includes('Posting configuration') ||
      submitError.includes('No posting configuration'))
      ? submitError
      : null

  const formatSchedulePosting = (row: Record<string, unknown>) => {
    const programmeCode = typeof row.programme_code === 'string' ? row.programme_code : ''
    const institution = typeof row.institution === 'string' ? row.institution : ''
    const startDate = typeof row.start_date === 'string' ? row.start_date : ''
    const endDate = typeof row.end_date === 'string' ? row.end_date : ''
    const scope = [programmeCode, institution].filter(Boolean).join(' - ')
    const dates = [startDate, endDate].filter(Boolean).join(' to ')
    return [scope, dates].filter(Boolean).join(' | ')
  }

  if (submitState === 'success' && registrationResult) {
    const resident = registrationResult.resident
    return (
      <main className="auth-stage registration-confirmation">
        <section className="auth-card auth-card-confirmation" aria-labelledby="registration-success-heading">
          <header className="auth-brand auth-brand-compact">
            <div className="auth-brand-mark auth-brand-mark-success">M</div>
            <div>
              <strong>MATA</strong>
              <span>Monitoring and Analysing of Teaching Attendances</span>
            </div>
          </header>

          <div className="auth-success-icon" aria-hidden="true">
            <IconCheck size={28} />
          </div>
          <div className="auth-confirmation-heading">
            <h1 id="registration-success-heading">You're registered</h1>
            <p>From now on, sign in with your MCR.</p>
          </div>

          <dl className="auth-confirmation-table">
            <div>
              <dt>Name</dt>
              <dd>{resident.name}</dd>
            </div>
            <div>
              <dt>MCR</dt>
              <dd className="mono">{resident.mcr}</dd>
            </div>
            <div>
              <dt>Home cluster</dt>
              <dd>{resident.homeCluster}</dd>
            </div>
            <div>
              <dt>NHG posting schedule</dt>
              <dd>
                {registrationResult.postingSchedule?.length ? (
                  <ul className="auth-confirmation-schedule">
                    {registrationResult.postingSchedule.map((row, index) => (
                      <li key={`${String(row.programme_code ?? 'posting')}-${index}`}>
                        {formatSchedulePosting(row)}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </dd>
            </div>
          </dl>

          <div className="auth-info-callout">
            <span aria-hidden="true">i</span>
            <p>
              <strong>Attendance routing:</strong> records are kept separate from NHG compliance and clawback.
            </p>
          </div>

          <button type="button" className="auth-confirmation-action" onClick={continueAfterSuccess}>
            {registrationResult.session ? 'Continue to portal' : 'Continue to login'}
          </button>
        </section>
      </main>
    )
  }

  return (
    <main className="auth-stage">
      <section className="auth-card auth-card-wide" aria-labelledby="non-nhg-registration-heading">
        <header className="auth-brand">
          <div className="auth-brand-mark">M</div>
          <div>
            <strong>MATA</strong>
            <span>Monitoring and Analysing of Teaching Attendances</span>
          </div>
        </header>

        <div className="auth-badge">Non-NHG Resident - First-time registration</div>
        <div className="auth-heading">
          <h1 id="non-nhg-registration-heading">Tell us about your posting</h1>
          <p>
            Non-NHG Residents from NUH and SingHealth posted to NHG departments register once.
            After this, you sign in with MCR only.
          </p>
        </div>

        <form className="auth-form" onSubmit={submitRegistration}>
          <label className="auth-field">
            <span>Full name</span>
            <input
              value={form.name}
              onChange={(event) => updateForm('name', event.target.value)}
              placeholder="e.g. Demo Resident"
              autoComplete="name"
            />
          </label>

          <label className="auth-field">
            <span>MCR number</span>
            <input
              className="mono"
              value={form.mcr}
              onChange={(event) => updateForm('mcr', event.target.value.toUpperCase())}
              placeholder="M12345X"
              autoComplete="username"
            />
            <small>Will be your login identifier going forward.</small>
          </label>

          <fieldset className="auth-fieldset">
            <legend>Home cluster</legend>
            <div className="auth-choice-grid">
              <button
                type="button"
                className={form.homeCluster === 'NUH' ? 'auth-choice is-active' : 'auth-choice'}
                onClick={() => updateForm('homeCluster', 'NUH')}
              >
                <strong>NUH</strong>
                <span>National University Health System</span>
              </button>
              <button
                type="button"
                className={form.homeCluster === 'SingHealth' ? 'auth-choice is-active' : 'auth-choice'}
                onClick={() => updateForm('homeCluster', 'SingHealth')}
              >
                <strong>SingHealth</strong>
                <span>Singapore Health Services</span>
              </button>
            </div>
            <small>Where you're a resident, not where you're currently posted.</small>
          </fieldset>

          <fieldset className="auth-fieldset auth-schedule-fieldset">
            <legend>Upcoming NHG Postings</legend>
            <small>Date-bounded NHG posting rows are used for future attendance and ad-hoc submissions.</small>
            <div className="auth-schedule-list">
              {form.postingSchedule.map((row, index) => (
                <div className="auth-schedule-row" key={row.id}>
                  <div className="auth-schedule-row-heading">
                    <strong>Posting {index + 1}</strong>
                    {form.postingSchedule.length > 1 ? (
                      <button type="button" onClick={() => removeScheduleRow(row.id)}>
                        Remove
                      </button>
                    ) : null}
                  </div>
                  <div className="auth-schedule-grid">
                    <label className="auth-field">
                      <span>Start date</span>
                      <input
                        type="date"
                        value={row.startDate}
                        onChange={(event) => updateScheduleRow(row.id, 'startDate', event.target.value)}
                      />
                    </label>
                    <label className="auth-field">
                      <span>End date</span>
                      <input
                        type="date"
                        value={row.endDate}
                        onChange={(event) => updateScheduleRow(row.id, 'endDate', event.target.value)}
                      />
                    </label>
                    <label className="auth-field">
                      <span>Programme</span>
                      <select
                        value={row.programmeCode}
                        onChange={(event) => selectScheduleProgramme(row.id, event.target.value)}
                      >
                        <option value="">Select programme</option>
                        {registrationOptions.programmes.map((option) => (
                          <option value={option.programmeCode} key={option.programmeCode}>
                            {option.programmeCode} - {option.programmeName}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="auth-field">
                      <span>Institution</span>
                      <select
                        value={row.institution}
                        onChange={(event) =>
                          updateScheduleRow(
                            row.id,
                            'institution',
                            event.target.value,
                          )
                        }
                        disabled={!row.programmeCode}
                      >
                        <option value="">Select institution</option>
                        {programmeInstitutionMappings(row.programmeCode).map((mapping) => (
                          <option
                            value={mapping.institutionCode}
                            key={mapping.institutionCode}
                            disabled={!mapping.available}
                          >
                            {institutionName(mapping.institutionCode)}
                            {mapping.status === 'pending' ? ' - configuration pending' : ''}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  {hasPendingMapping(row) ? (
                    <div className="auth-info-callout" role="status">
                      <span aria-hidden="true">i</span>
                      <p>{PENDING_MAPPING_MESSAGE}</p>
                    </div>
                  ) : null}
                  {postingResolutionError ? (
                    <div className="auth-schedule-row-error" role="alert">
                      {postingResolutionError}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
            {registrationOptionsLoading ? (
              <div className="auth-info-callout" role="status">
                <span aria-hidden="true">i</span>
                <p>Loading posting options...</p>
              </div>
            ) : null}
            {registrationOptionsError ? (
              <div className="auth-schedule-row-error" role="alert">
                {registrationOptionsError}
              </div>
            ) : null}
            {!registrationOptionsLoading &&
            !registrationOptionsError &&
            registrationOptions.institutions.length === 0 ? (
              <div className="auth-info-callout" role="status">
                <span aria-hidden="true">i</span>
                <p>{NO_CONFIGURED_INSTITUTIONS}</p>
              </div>
            ) : null}
            <button
              type="button"
              className="auth-schedule-add"
              onClick={addScheduleRow}
              disabled={
                registrationOptionsLoading ||
                registrationOptions.institutions.length === 0
              }
            >
              Add posting row
            </button>
          </fieldset>

          <div className="auth-info-callout">
            <span aria-hidden="true">i</span>
            <p>
              <strong>What happens next</strong>
              Your account is created as a Non-NHG Resident. Attendance is recorded separately and not included in
              NHG compliance.
            </p>
          </div>

          {submitError ? <div className="auth-error" role="alert">{submitError}</div> : null}

          <div className="auth-form-actions">
            <Link className="auth-secondary-link" to="/login">Cancel</Link>
            <button className="auth-primary-action auth-primary-action-inline" type="submit" disabled={!canSubmit || submitState === 'submitting'}>
              {submitState === 'submitting' ? 'Creating account...' : 'Create Non-NHG account'}
              <IconChevRight size={15} />
            </button>
          </div>
        </form>
      </section>
    </main>
  )
}
