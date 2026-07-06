import { useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { STAFF_SUPABASE_BACKEND_AUTH_ERROR, loginResident, loginStaff } from '../../api/auth'
import { ApiRequestError } from '../../api/http'
import { IconChevRight } from '../../components/icons'
import { defaultPathForRole, isPathAllowedForRole } from '../../config/navigation'
import { useAuth } from '../../context/useAuth'
import type { AppRole } from '../../types/app'

type ResidentLoginRole = 'resident' | 'external_resident'
type LoginFormId = 'staff' | 'resident'

const LOGIN_ERROR = 'Unable to sign in. Check your details and try again.'
const RESIDENT_HELP =
  'NHG and registered Non-NHG Residents use MCR-only sign-in for their own resident routes.'
const SUPABASE_CONFIGURATION_ERROR_MARKER = 'VITE_AUTH_MODE=supabase requires'

const getRedirectPath = (role: AppRole, from?: string) => {
  if (from && isPathAllowedForRole(from, role)) {
    return from
  }
  return defaultPathForRole(role)
}

const getStaffLoginErrorMessage = (loginError: unknown) => {
  if (!(loginError instanceof ApiRequestError)) {
    return LOGIN_ERROR
  }
  if (
    loginError.message.includes(SUPABASE_CONFIGURATION_ERROR_MARKER) ||
    loginError.message.includes(STAFF_SUPABASE_BACKEND_AUTH_ERROR)
  ) {
    return loginError.message
  }
  return LOGIN_ERROR
}

export const LoginPage = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const { loginWithSession, logout } = useAuth()
  const fromPath = (location.state as { from?: string } | null)?.from

  const [staffEmail, setStaffEmail] = useState('')
  const [staffPassword, setStaffPassword] = useState('')
  const [residentMcr, setResidentMcr] = useState('')
  const [error, setError] = useState<{ formId: LoginFormId; message: string } | null>(null)
  const [submittingForm, setSubmittingForm] = useState<LoginFormId | null>(null)
  const isSubmitting = submittingForm !== null

  const submitStaffLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!staffEmail.trim() || !staffPassword) {
      setError({ formId: 'staff', message: LOGIN_ERROR })
      return
    }

    setSubmittingForm('staff')
    setError(null)
    await logout()
    try {
      const session = await loginStaff(staffEmail, staffPassword)
      loginWithSession(session)
      navigate(getRedirectPath(session.identity.role, fromPath), { replace: true })
    } catch (loginError) {
      await logout()
      setError({ formId: 'staff', message: getStaffLoginErrorMessage(loginError) })
    } finally {
      setSubmittingForm(null)
    }
  }

  const submitResidentLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!residentMcr.trim()) {
      setError({ formId: 'resident', message: LOGIN_ERROR })
      return
    }

    const normalisedMcr = residentMcr.trim().toUpperCase()
    const loginOrder: ResidentLoginRole[] = normalisedMcr.startsWith('E')
      ? ['external_resident', 'resident']
      : ['resident', 'external_resident']

    setSubmittingForm('resident')
    setError(null)
    await logout()
    try {
      for (const role of loginOrder) {
        try {
          const session = await loginResident(normalisedMcr, role)
          loginWithSession(session)
          navigate(getRedirectPath(session.identity.role, fromPath), { replace: true })
          return
        } catch {
          // Try the other resident identity table before showing the generic failure.
        }
      }
      await logout()
      setError({ formId: 'resident', message: LOGIN_ERROR })
    } catch {
      await logout()
      setError({ formId: 'resident', message: LOGIN_ERROR })
    } finally {
      setSubmittingForm(null)
    }
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
            <span>Medical Attendance Tracking</span>
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

        <form className="auth-form auth-form-block" onSubmit={submitResidentLogin}>
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

          <p className="auth-help">
            {RESIDENT_HELP}
          </p>

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
