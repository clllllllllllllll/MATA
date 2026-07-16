import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import {
  STAFF_SUPABASE_BACKEND_AUTH_ERROR,
  loginResident,
  loginStaff,
} from '../../api/auth'
import { ApiRequestError } from '../../api/http'
import {
  GENERIC_LOGIN_ERROR,
  getRateLimitLoginErrorMessage,
  resolveResidentLoginError,
} from '../../api/loginErrorMessages'
import { IconChevRight } from '../../components/icons'
import { defaultPathForRole, isPathAllowedForRole } from '../../config/navigation'
import { useAuth } from '../../context/useAuth'
import type { AppRole } from '../../types/app'
import {
  createInitialResidentLoginState,
  selectResidentLoginRole,
  submitSelectedResidentLogin,
} from './residentLoginFlow'
import type { ResidentLoginRole } from '../../api/loginPayloads'
type LoginFormId = 'staff' | 'resident'

const RESIDENT_HELP =
  'Use NHG Resident for RDB-backed resident accounts. Registered Non-NHG Residents must choose their separate sign-in mode.'
const SUPABASE_CONFIGURATION_ERROR_MARKER = 'VITE_AUTH_MODE=supabase requires'

const getRedirectPath = (role: AppRole, from?: string) => {
  if (from && isPathAllowedForRole(from, role)) {
    return from
  }
  return defaultPathForRole(role)
}

const getStaffLoginErrorMessage = (loginError: unknown) => {
  const rateLimitMessage = getRateLimitLoginErrorMessage(loginError)
  if (rateLimitMessage) {
    return rateLimitMessage
  }
  if (!(loginError instanceof ApiRequestError)) {
    return GENERIC_LOGIN_ERROR
  }
  if (
    loginError.message.includes(SUPABASE_CONFIGURATION_ERROR_MARKER) ||
    loginError.message.includes(STAFF_SUPABASE_BACKEND_AUTH_ERROR)
  ) {
    return loginError.message
  }
  return GENERIC_LOGIN_ERROR
}

export const LoginPage = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const { beginLoginAttempt, isAuthRequestCurrent, clearCurrentAuthRequest, loginWithSession } = useAuth()
  const fromPath = (location.state as { from?: string } | null)?.from

  const [staffEmail, setStaffEmail] = useState('')
  const [staffPassword, setStaffPassword] = useState('')
  const [residentMcr, setResidentMcr] = useState('')
  const [residentLoginState, setResidentLoginState] = useState(createInitialResidentLoginState)
  const [error, setError] = useState<{ formId: LoginFormId; message: string } | null>(null)
  const [submittingForm, setSubmittingForm] = useState<LoginFormId | null>(null)
  const isSubmitting = submittingForm !== null

  const submitStaffLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submittingForm === 'staff') {
      return
    }
    if (!staffEmail.trim() || !staffPassword) {
      setError({ formId: 'staff', message: GENERIC_LOGIN_ERROR })
      return
    }

    setSubmittingForm('staff')
    setError(null)
    const loginGeneration = beginLoginAttempt()
    try {
      const session = await loginStaff(staffEmail, staffPassword)
      if (!isAuthRequestCurrent(loginGeneration)) {
        return
      }
      setSubmittingForm(null)
      loginWithSession(session)
      navigate(getRedirectPath(session.identity.role, fromPath), { replace: true })
    } catch (loginError) {
      if (!isAuthRequestCurrent(loginGeneration)) {
        return
      }
      const clearedCurrentRequest = await clearCurrentAuthRequest(loginGeneration, { signOutSupabase: true })
      if (!clearedCurrentRequest) {
        return
      }
      setError({ formId: 'staff', message: getStaffLoginErrorMessage(loginError) })
    } finally {
      if (isAuthRequestCurrent(loginGeneration)) {
        setSubmittingForm(null)
      }
    }
  }

  const submitResidentLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submittingForm === 'resident') {
      return
    }
    if (!residentMcr.trim()) {
      setError({ formId: 'resident', message: GENERIC_LOGIN_ERROR })
      return
    }

    setSubmittingForm('resident')
    setError(null)
    const loginGeneration = beginLoginAttempt()
    try {
      const result = await submitSelectedResidentLogin({
        rawMcr: residentMcr,
        role: residentLoginState.role,
        authenticate: loginResident,
      })
      if (!isAuthRequestCurrent(loginGeneration)) {
        return
      }
      setSubmittingForm(null)
      loginWithSession(result.session)
      navigate(result.redirectPath, { replace: true })
    } catch (loginError) {
      if (!isAuthRequestCurrent(loginGeneration)) {
        return
      }
      const clearedCurrentRequest = await clearCurrentAuthRequest(loginGeneration)
      if (!clearedCurrentRequest) {
        return
      }
      setError({ formId: 'resident', message: resolveResidentLoginError(loginError) })
    } finally {
      if (isAuthRequestCurrent(loginGeneration)) {
        setSubmittingForm(null)
      }
    }
  }

  const chooseResidentLoginRole = (role: ResidentLoginRole) => {
    if (submittingForm === 'resident') {
      return
    }
    setResidentLoginState(selectResidentLoginRole(role))
    setError((currentError) => currentError?.formId === 'resident' ? null : currentError)
  }

  const formError = (formId: LoginFormId) =>
    error?.formId === formId ? <div className="auth-error" role="alert">{error.message}</div> : null

  return (
    <main className="auth-stage">
      <section className="auth-card login-card" aria-labelledby="login-heading">
        <header className="auth-brand">
          <div className="auth-brand-mark">M</div>
          <div>
            <strong>MATA</strong>
            <span>Monitoring and Analysing of Teaching Attendances</span>
          </div>
        </header>

        <div className="auth-heading">
          <h1 id="login-heading">Sign in</h1>
          <p>
            Staff use email and password. NHG Residents and registered Non-NHG Residents use MCR-only sign-in.
          </p>
        </div>

        <form
          className="auth-form auth-form-block"
          onSubmit={submitStaffLogin}
          aria-labelledby="staff-login-heading"
        >
          <div className="auth-section-heading">
            <h2 id="staff-login-heading">Staff login</h2>
            <p>Email and password for assigned staff accounts.</p>
          </div>

          <label className="auth-field">
            <span>Email</span>
            <input
              type="email"
              value={staffEmail}
              onChange={(event) => setStaffEmail(event.target.value)}
              placeholder="demo.admin@example.com"
              autoComplete="username"
            />
          </label>
          <label className="auth-field">
            <span>Password</span>
            <input
              type="password"
              value={staffPassword}
              onChange={(event) => setStaffPassword(event.target.value)}
              placeholder="Password"
              autoComplete="current-password"
            />
          </label>

          {formError('staff')}

          <button className="auth-primary-action" type="submit" disabled={isSubmitting}>
            {submittingForm === 'staff' ? 'Signing in...' : 'Sign in'}
            <IconChevRight size={15} />
          </button>
        </form>

        <div className="auth-divider">Resident MCR</div>

        <div className="auth-resident-role-selector" role="group" aria-label="Resident account type">
          <button
            type="button"
            className={residentLoginState.role === 'resident' ? 'is-active' : ''}
            aria-pressed={residentLoginState.role === 'resident'}
            onClick={() => chooseResidentLoginRole('resident')}
            disabled={isSubmitting}
          >
            NHG Resident
          </button>
          <button
            type="button"
            className={residentLoginState.role === 'external_resident' ? 'is-active' : ''}
            aria-pressed={residentLoginState.role === 'external_resident'}
            onClick={() => chooseResidentLoginRole('external_resident')}
            disabled={isSubmitting}
          >
            Registered Non-NHG Resident
          </button>
        </div>

        <form className="auth-form auth-form-block" onSubmit={submitResidentLogin}>
          <div className="auth-section-heading">
            <h2>
              {residentLoginState.role === 'resident'
                ? 'NHG Resident login'
                : 'Registered Non-NHG Resident login'}
            </h2>
            <p>{RESIDENT_HELP}</p>
          </div>
          <label className="auth-field">
            <span>MCR number</span>
            <input
              className="mono"
              value={residentMcr}
              onChange={(event) => setResidentMcr(event.target.value.toUpperCase())}
              placeholder="e.g. M00001A"
              autoComplete="username"
            />
          </label>

          {formError('resident')}

          <button
            className="auth-primary-action auth-primary-action-resident"
            type="submit"
            disabled={isSubmitting}
          >
            {submittingForm === 'resident' ? 'Signing in...' : 'Continue'}
            <IconChevRight size={15} />
          </button>
        </form>

        <div className="auth-divider">or</div>

        <Link className="auth-register-cta" to="/register/non-nhg">
          <span>
            <strong>I am a Non-NHG Resident posted to NHG</strong>
            <small>First-time NUH / SingHealth residents register here. Future logins use MCR only.</small>
          </span>
          <IconChevRight size={16} />
        </Link>
      </section>
    </main>
  )
}
