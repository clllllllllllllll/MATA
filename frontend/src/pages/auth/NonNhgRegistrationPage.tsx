import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { registerNonNhgResident, type NonNhgRegistrationResult } from '../../api/auth'
import { ApiRequestError } from '../../api/http'
import { IconCheck, IconChevRight } from '../../components/icons'
import { defaultPathForRole } from '../../config/navigation'
import { useAuth } from '../../context/useAuth'

type HomeCluster = 'NUH' | 'SingHealth'

interface RegistrationFormState {
  name: string
  mcr: string
  homeCluster: HomeCluster | ''
  currentNhgPostingCode: string
}

const INITIAL_FORM: RegistrationFormState = {
  name: '',
  mcr: '',
  homeCluster: '',
  currentNhgPostingCode: '',
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
    form.currentNhgPostingCode.trim().length > 0

  const updateForm = <Key extends keyof RegistrationFormState>(
    key: Key,
    value: RegistrationFormState[Key],
  ) => {
    setForm((prev) => ({ ...prev, [key]: value }))
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
        currentNhgPostingCode: form.currentNhgPostingCode,
      })
      setRegistrationResult(result)
      setSubmitState('success')
    } catch (error) {
      const message =
        error instanceof ApiRequestError && error.status === 422
          ? REGISTER_ERROR
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
              <dt>NHG posting</dt>
              <dd>{resident.currentNhgPostingCode}</dd>
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

          <label className="auth-field">
            <span>Current NHG posting</span>
            <input
              className="mono"
              value={form.currentNhgPostingCode}
              onChange={(event) => updateForm('currentNhgPostingCode', event.target.value.trim())}
              placeholder="e.g. TTSHGerMed"
            />
            <small>Where you're posted right now within NHG. Backend validation is authoritative.</small>
          </label>

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
