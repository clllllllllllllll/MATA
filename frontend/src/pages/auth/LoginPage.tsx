import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { loginResident, loginStaff } from '../../api/auth'
import {
  GENERIC_LOGIN_ERROR,
  getRateLimitLoginErrorMessage,
  resolveResidentLoginError,
} from '../../api/loginErrorMessages'
import { IconChevRight } from '../../components/icons'
import { defaultPathForRole, isPathAllowedForRole } from '../../config/navigation'
import { useAuth } from '../../context/useAuth'
import type { AppRole } from '../../types/app'
import { submitSharedResidentLogin } from './residentLoginFlow'
type LoginFormId = 'staff' | 'resident'

const RESIDENT_HELP =
  'NHG and registered Non-NHG residents use this shared MCR login.'
const LOGOUT_STATUS_REVEAL_DELAY_MS = 700

const getRedirectPath = (role: AppRole, from?: string) => {
  if (from && isPathAllowedForRole(from, role)) {
    return from
  }
  return defaultPathForRole(role)
}

const getStaffLoginErrorMessage = (loginError: unknown) => {
  const rateLimitMessage = getRateLimitLoginErrorMessage(loginError)
  return rateLimitMessage ?? GENERIC_LOGIN_ERROR
}

export const LoginPage = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const {
    beginLoginAttempt,
    isAuthRequestCurrent,
    clearCurrentAuthRequest,
    loginWithSession,
    logoutStatus,
    isLogoutRetrying,
    canRetryLogout,
    logoutRetryReason,
    retryLogout,
  } = useAuth()
  const fromPath = (location.state as { from?: string } | null)?.from
  const logoutStatusHeadingRef = useRef<HTMLHeadingElement | null>(null)
  const submitAttemptRef = useRef(0)

  const [staffEmail, setStaffEmail] = useState('')
  const [staffPassword, setStaffPassword] = useState('')
  const [residentMcr, setResidentMcr] = useState('')
  const [error, setError] = useState<{ formId: LoginFormId; message: string } | null>(null)
  const [submittingForm, setSubmittingForm] = useState<LoginFormId | null>(null)
  const [showLogoutStatus, setShowLogoutStatus] = useState(false)
  const isSubmitting = submittingForm !== null
  const shouldRevealLogoutStatus =
    logoutStatus === 'pending'
    && !isLogoutRetrying
    && logoutRetryReason !== 'retry-scheduled'

  useEffect(() => {
    if (!shouldRevealLogoutStatus) {
      return
    }
    const revealTimer = window.setTimeout(() => {
      setShowLogoutStatus(true)
    }, LOGOUT_STATUS_REVEAL_DELAY_MS)
    return () => window.clearTimeout(revealTimer)
  }, [shouldRevealLogoutStatus])

  useEffect(() => {
    if (showLogoutStatus) {
      logoutStatusHeadingRef.current?.focus()
    }
  }, [showLogoutStatus])

  const submitStaffLogin = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (submittingForm === 'staff') {
      return
    }
    if (!staffEmail.trim() || !staffPassword) {
      setError({ formId: 'staff', message: GENERIC_LOGIN_ERROR })
      return
    }

    const submitAttempt = submitAttemptRef.current + 1
    submitAttemptRef.current = submitAttempt
    setSubmittingForm('staff')
    setError(null)
    const loginGeneration = beginLoginAttempt()
    try {
      let loginCommitted = false
      const session = await loginStaff(staffEmail, staffPassword, (nextSession) => {
        loginCommitted = loginWithSession(nextSession, loginGeneration)
        return loginCommitted
      })
      if (!isAuthRequestCurrent(loginGeneration)) {
        return
      }
      if (!loginCommitted) {
        return
      }
      setSubmittingForm(null)
      navigate(getRedirectPath(session.identity.role, fromPath), { replace: true })
    } catch (loginError) {
      if (!isAuthRequestCurrent(loginGeneration)) {
        return
      }
      const clearedCurrentRequest = await clearCurrentAuthRequest(loginGeneration)
      if (!clearedCurrentRequest) {
        return
      }
      setError({ formId: 'staff', message: getStaffLoginErrorMessage(loginError) })
    } finally {
      if (submitAttemptRef.current === submitAttempt) {
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

    const submitAttempt = submitAttemptRef.current + 1
    submitAttemptRef.current = submitAttempt
    setSubmittingForm('resident')
    setError(null)
    const loginGeneration = beginLoginAttempt()
    try {
      let loginCommitted = false
      const result = await submitSharedResidentLogin({
        rawMcr: residentMcr,
        authenticate: (payload) => loginResident(payload, (nextSession) => {
          if (
            nextSession.identity.role !== 'resident'
            && nextSession.identity.role !== 'external_resident'
          ) {
            return false
          }
          loginCommitted = loginWithSession(nextSession, loginGeneration)
          return loginCommitted
        }),
      })
      if (!isAuthRequestCurrent(loginGeneration)) {
        return
      }
      if (!loginCommitted) {
        return
      }
      setSubmittingForm(null)
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
      if (submitAttemptRef.current === submitAttempt) {
        setSubmittingForm(null)
      }
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
            <span>Monitoring and Analysing of Teaching Attendances</span>
          </div>
        </header>

        <div className="auth-heading">
          <h1 id="login-heading">Sign in</h1>
          <p>
            Staff use email and password. NHG Residents and registered Non-NHG Residents use MCR-only sign-in.
          </p>
        </div>

        {shouldRevealLogoutStatus && showLogoutStatus ? (
          <section
            className="auth-logout-status auth-logout-status-pending"
            role="alert"
            aria-live="assertive"
          >
            <h2 ref={logoutStatusHeadingRef} tabIndex={-1}>
              Server sign-out not confirmed
            </h2>
            <p>
              Your local identity and protected data were cleared immediately.
              Protected requests and session restoration remain blocked until
              server sign-out is confirmed or you successfully sign in again.
            </p>
            {logoutRetryReason === 'offline' ? (
              <p>Reconnect to continue the bounded server sign-out retry.</p>
            ) : null}
            {canRetryLogout ? (
              <button
                type="button"
                className="auth-logout-retry"
                onClick={() => retryLogout()}
              >
                Retry server sign-out
              </button>
            ) : (
              <p>
                {logoutRetryReason === 'no-proof'
                  ? 'The sign-out proof is no longer available after reload. '
                  : 'No further retry is available in this tab. '}
                Use either sign-in form below to establish a replacement session.
              </p>
            )}
          </section>
        ) : null}

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
              placeholder="e.g. M12345A"
              autoComplete="username"
            />
          </label>

          <p className="auth-help">{RESIDENT_HELP}</p>

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
