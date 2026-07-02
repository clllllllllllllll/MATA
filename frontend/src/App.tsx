import { Navigate, Route, Routes } from 'react-router-dom'
import type { ReactElement } from 'react'
import { AppShell } from './components/AppShell'
import { useLocation } from 'react-router-dom'
import { AdminConfigPage } from './pages/admin/AdminConfigPage'
import { AdminHomePage } from './pages/admin/AdminHomePage'
import { AdminLogsPage } from './pages/admin/AdminLogsPage'
import { AdminMultiPostingPage } from './pages/admin/AdminMultiPostingPage'
import { AdminParsedDataPage } from './pages/admin/AdminParsedDataPage'
import { AdminResidentSubmissionsPage } from './pages/admin/AdminResidentSubmissionsPage'
import { AdminSecretaryEventsPage } from './pages/admin/AdminSecretaryEventsPage'
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

const AccessControlledRoutes = () => {
  const { authState, hasExplicitSession, isLoading } = useAuth()
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
            subtitle="Optional visual stub. Non-NHG Resident implementation is deferred."
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



