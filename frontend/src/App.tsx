import { Navigate, Route, Routes } from 'react-router-dom'
import { useState, type FormEvent, type ReactElement } from 'react'
import { AppShell } from './components/AppShell'
import { useLocation } from 'react-router-dom'
import { AdminConfigPage } from './pages/admin/AdminConfigPage'
import { AdminHomePage } from './pages/admin/AdminHomePage'
import { AdminLogsPage } from './pages/admin/AdminLogsPage'
import { AdminMultiPostingPage } from './pages/admin/AdminMultiPostingPage'
import { AdminParsedDataPage } from './pages/admin/AdminParsedDataPage'
import { AdminResidentSubmissionsPage } from './pages/admin/AdminResidentSubmissionsPage'
import { AdminSecretaryEventsPage } from './pages/admin/AdminSecretaryEventsPage'
import { AdminStaffAccountsPage } from './pages/admin/AdminStaffAccountsPage'
import { AdminUploadLogsPage } from './pages/admin/AdminUploadLogsPage'
import { AdminUploadPage } from './pages/admin/AdminUploadPage'
import { AdminWarningsPage } from './pages/admin/AdminWarningsPage'
import { PcTeachingEventsPage } from './pages/pc/PcTeachingEventsPage'
import { PcUploadTtfPage } from './pages/pc/PcUploadTtfPage'
import { ResidentAttendancePage } from './pages/resident/ResidentAttendancePage'
import { ResidentSubmissionPage } from './pages/resident/ResidentSubmissionPage'
import { SecretaryTeachingSchedulePage } from './pages/secretary/SecretaryTeachingSchedulePage'
import { StubPage } from './pages/StubPage'
import { useAuth } from './context/useAuth'
import { LoginPage } from './pages/auth/LoginPage'
import { NonNhgRegistrationPage } from './pages/auth/NonNhgRegistrationPage'
import { getRouteAccessDecision, shouldRenderRoutes } from './routeGuards'

const AuthLoadingScreen = () => (
  <div className="auth-hydration-screen" aria-live="polite" aria-label="Checking session">
    <span className="auth-hydration-dot" aria-hidden="true" />
  </div>
)

const isStaffIdentity = (identity: ReturnType<typeof useAuth>['identity']) =>
  identity?.role === 'master_admin' ||
  identity?.role === 'programme_pc' ||
  identity?.role === 'secretary'

const StaffActorNameGate = () => {
  const { logout, updateStaffActorName } = useAuth()
  const [fullName, setFullName] = useState('')
  const [isSaving, setIsSaving] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmedName = fullName.trim()
    if (!trimmedName) {
      setErrorMessage('Full name is required.')
      return
    }

    setIsSaving(true)
    setErrorMessage(null)
    try {
      await updateStaffActorName(trimmedName)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Unable to save staff name.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <div className="staff-actor-gate">
      <form className="staff-actor-card" onSubmit={(event) => void handleSubmit(event)}>
        <h1>Set staff name</h1>
        <p>This name will be recorded on actions performed using this shared staff account. You can change it later from Settings.</p>
        <label className="auth-field">
          <span>Full name</span>
          <input
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            autoComplete="name"
            disabled={isSaving}
          />
        </label>
        {errorMessage ? <div className="auth-error">{errorMessage}</div> : null}
        <div className="staff-actor-actions">
          <button type="submit" className="button button-primary" disabled={isSaving}>
            {isSaving ? 'Saving' : 'Save and continue'}
          </button>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void logout()}
            disabled={isSaving}
          >
            Log out
          </button>
        </div>
      </form>
    </div>
  )
}

const AccessControlledRoutes = () => {
  const { authState, hasExplicitSession, identity, isLoading, staffActorNameRequired } = useAuth()
  const location = useLocation()
  const decision = getRouteAccessDecision({
    pathname: location.pathname,
    isLoading,
    hasExplicitSession,
    role: authState.role,
  })

  if (decision.kind === 'wait_for_auth_hydration') {
    return <AuthLoadingScreen />
  }

  if (decision.kind === 'redirect_to_login') {
    return (
      <Navigate
        to={decision.to}
        replace
        state={decision.to === '/login' ? { from: location.pathname } : undefined}
      />
    )
  }

  if (decision.kind === 'redirect_to_role_default') {
    return <Navigate to={decision.to} replace />
  }

  if (!shouldRenderRoutes(decision)) {
    return null
  }

  if (staffActorNameRequired && isStaffIdentity(identity)) {
    return <StaffActorNameGate />
  }

  return <AppRoutes />
}

const shellElement = (children: ReactElement) => <AppShell>{children}</AppShell>

const AppRoutes = () => {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/login" replace />} />
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register/non-nhg" element={<NonNhgRegistrationPage />} />
      <Route path="/non-nhg/register" element={<Navigate to="/register/non-nhg" replace />} />
      <Route path="/admin" element={shellElement(<AdminHomePage />)} />
      <Route path="/admin/upload" element={shellElement(<AdminUploadPage />)} />
      <Route path="/admin/upload/warnings" element={shellElement(<AdminWarningsPage />)} />
      <Route path="/admin/config" element={shellElement(<AdminConfigPage configViewRole="master_admin" />)} />
      <Route path="/admin/config/multi" element={shellElement(<AdminMultiPostingPage />)} />
      <Route path="/admin/logs" element={shellElement(<AdminLogsPage />)} />
      <Route path="/admin/upload-logs" element={shellElement(<AdminUploadLogsPage />)} />
      <Route path="/admin/parsed-data" element={shellElement(<AdminParsedDataPage />)} />
      <Route path="/admin/secretary-events" element={shellElement(<AdminSecretaryEventsPage />)} />
      <Route path="/admin/staff-accounts" element={shellElement(<AdminStaffAccountsPage />)} />
      <Route path="/admin/submissions" element={shellElement(<AdminResidentSubmissionsPage />)} />
      <Route path="/pc" element={shellElement(<Navigate to="/pc/teaching-events" replace />)} />
      <Route path="/pc/upload-ttf" element={shellElement(<PcUploadTtfPage />)} />
      <Route path="/pc/teaching-events" element={shellElement(<PcTeachingEventsPage />)} />
      <Route path="/pc/config" element={shellElement(<AdminConfigPage configViewRole="programme_pc" />)} />
      <Route path="/pc/warnings" element={shellElement(<AdminWarningsPage />)} />
      <Route path="/secretary" element={shellElement(<Navigate to="/secretary/events" replace />)} />
      <Route path="/secretary/events" element={shellElement(<SecretaryTeachingSchedulePage />)} />
      <Route path="/resident" element={shellElement(<Navigate to="/resident/submissions" replace />)} />
      <Route path="/resident/submissions" element={shellElement(<ResidentSubmissionPage />)} />
      <Route path="/resident/attendance" element={shellElement(<ResidentAttendancePage />)} />
      <Route
        path="/external"
        element={shellElement((
          <StubPage
            title="Non-NHG Resident Portal"
            subtitle="Optional visual stub. Non-NHG Resident submission workflows remain deferred."
            variant="non_nhg"
          />
        ))}
      />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  )
}

function App() {
  return <AccessControlledRoutes />
}

export default App



