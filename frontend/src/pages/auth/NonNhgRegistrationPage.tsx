import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { registerNonNhgResident, type NonNhgRegistrationResult } from '../../api/auth'
import { ApiRequestError } from '../../api/http'
import { IconCheck, IconChevRight } from '../../components/icons'
import { defaultPathForRole } from '../../config/navigation'
import { useAuth } from '../../context/useAuth'

type HomeCluster = 'NUH' | 'SingHealth'
type ScheduleInstitution = 'TTSH' | 'WH' | 'KTPH'

interface PostingScheduleRowState {
  id: string
  startDate: string
  endDate: string
  programmeCode: string
  institution: ScheduleInstitution
}

interface RegistrationFormState {
  name: string
  mcr: string
  homeCluster: HomeCluster | ''
  postingSchedule: PostingScheduleRowState[]
}

const PROGRAMME_OPTIONS = [
  ['AIM', 'Advanced Internal Medicine'],
  ['ANAES', 'Anaesthesiology'],
  ['CARDIO', 'Cardiology'],
  ['DERM', 'Dermatology'],
  ['DR', 'Diagnostic Radiology'],
  ['EM', 'Emergency Medicine'],
  ['ENDO', 'Endocrinology'],
  ['ENT', 'Otorhinolaryngology'],
  ['EYE', 'Ophthalmology'],
  ['FM', 'Family Medicine'],
  ['GASTRO', 'Gastroenterology'],
  ['GERI', 'Geriatric Medicine'],
  ['GS', 'General Surgery'],
  ['ID', 'Infectious Diseases'],
  ['IM', 'Internal Medicine'],
  ['MEDONCO', 'Medical Oncology'],
  ['ORTHO', 'Orthopaedic Surgery'],
  ['PATH', 'Pathology'],
  ['PSY', 'Psychiatry'],
  ['REHAB', 'Rehabilitation Medicine'],
  ['RENAL', 'Renal Medicine'],
  ['RESPI', 'Respiratory Medicine'],
  ['RHEUM', 'Rheumatology'],
  ['SPORTSMED', 'Sports Medicine'],
  ['SIG', 'Surgery-In-General'],
  ['URO', 'Urology'],
  ['MICROB', 'Pathology (Microbiology)'],
  ['PALLMED', 'Palliative Medicine'],
] as const

const INSTITUTION_OPTIONS: ScheduleInstitution[] = ['TTSH', 'WH', 'KTPH']

const createScheduleRow = (id: string): PostingScheduleRowState => ({
  id,
  startDate: '',
  endDate: '',
  programmeCode: '',
  institution: 'TTSH',
})

const INITIAL_FORM: RegistrationFormState = {
  name: '',
  mcr: '',
  homeCluster: '',
  postingSchedule: [createScheduleRow('posting-1')],
}

const REGISTER_ERROR = 'Unable to register. Check your details and try again.'

export const NonNhgRegistrationPage = () => {
  const navigate = useNavigate()
  const { loginWithSession } = useAuth()
  const [form, setForm] = useState<RegistrationFormState>(INITIAL_FORM)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'success' | 'error'>('idle')
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [registrationResult, setRegistrationResult] = useState<NonNhgRegistrationResult | null>(null)

  const canSubmit =
    form.name.trim().length > 0 &&
    form.mcr.trim().length > 0 &&
    Boolean(form.homeCluster) &&
    form.postingSchedule.every((row) =>
      row.startDate &&
      row.endDate &&
      row.startDate <= row.endDate &&
      row.programmeCode &&
      row.institution,
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
      const message =
        error instanceof ApiRequestError &&
        error.status === 422 &&
        (error.message.includes('No posting could be resolved') ||
          error.message.includes('Multiple postings could be resolved'))
          ? error.message
          : REGISTER_ERROR
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
    (submitError.includes('No posting could be resolved') ||
      submitError.includes('Multiple postings could be resolved'))
      ? submitError
      : null

  const formatSchedulePosting = (row: Record<string, unknown>) => {
    const postingCode = typeof row.posting_code === 'string' ? row.posting_code : ''
    const programmeCode = typeof row.programme_code === 'string' ? row.programme_code : ''
    const institution = typeof row.institution === 'string' ? row.institution : ''
    const startDate = typeof row.start_date === 'string' ? row.start_date : ''
    const endDate = typeof row.end_date === 'string' ? row.end_date : ''
    const scope = [programmeCode, institution].filter(Boolean).join(' - ')
    const dates = [startDate, endDate].filter(Boolean).join(' to ')
    return [postingCode, scope, dates].filter(Boolean).join(' | ')
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
              <span>Medical Attendance Tracking</span>
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
                      <li key={`${String(row.posting_code ?? 'posting')}-${index}`}>
                        {formatSchedulePosting(row)}
                      </li>
                    ))}
                  </ul>
                ) : (
                  resident.currentNhgPostingCode
                )}
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
            <span>Medical Attendance Tracking</span>
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
                        onChange={(event) => updateScheduleRow(row.id, 'programmeCode', event.target.value)}
                      >
                        <option value="">Select programme</option>
                        {PROGRAMME_OPTIONS.map(([code, name]) => (
                          <option value={code} key={code}>
                            {code} - {name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="auth-field">
                      <span>Institution</span>
                      <select
                        value={row.institution}
                        onChange={(event) =>
                          updateScheduleRow(row.id, 'institution', event.target.value as ScheduleInstitution)
                        }
                      >
                        {INSTITUTION_OPTIONS.map((institution) => (
                          <option value={institution} key={institution}>
                            {institution}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>
                  {postingResolutionError ? (
                    <div className="auth-schedule-row-error" role="alert">
                      {postingResolutionError}
                    </div>
                  ) : null}
                </div>
              ))}
            </div>
            <button type="button" className="auth-schedule-add" onClick={addScheduleRow}>
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
