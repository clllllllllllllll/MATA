import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { AdminConfigPage } from './pages/admin/AdminConfigPage'
import { AdminHomePage } from './pages/admin/AdminHomePage'
import { AdminMultiPostingPage } from './pages/admin/AdminMultiPostingPage'
import { AdminPlaceholderPage } from './pages/admin/AdminPlaceholderPage'
import { AdminUploadPage } from './pages/admin/AdminUploadPage'
import { AdminWarningsPage } from './pages/admin/AdminWarningsPage'
import { ResidentSubmissionPage } from './pages/resident/ResidentSubmissionPage'
import { SecretaryTeachingSchedulePage } from './pages/secretary/SecretaryTeachingSchedulePage'
import { StubPage } from './pages/StubPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/admin" replace />} />
      <Route element={<AppShell />}>
        <Route path="/admin" element={<AdminHomePage />} />
        <Route path="/admin/upload" element={<AdminUploadPage />} />
        <Route path="/admin/upload/warnings" element={<AdminWarningsPage />} />
        <Route path="/admin/config" element={<AdminConfigPage />} />
        <Route path="/admin/config/multi" element={<AdminMultiPostingPage />} />
        <Route
          path="/admin/upload-logs"
          element={
            <AdminPlaceholderPage
              title="Upload Logs"
              subtitle="Master Admin - Upload audit trail"
              note="Upload log viewing is pending backend endpoint support for persisted upload_logs records."
            />
          }
        />
        <Route
          path="/admin/parsed"
          element={
            <AdminPlaceholderPage
              title="Parsed Data"
              subtitle="Master Admin - Parser output review"
              note="Parsed data review tables are pending implementation and should be wired only after the related backend read endpoints are available."
            />
          }
        />
        <Route
          path="/admin/secretary-events"
          element={
            <AdminPlaceholderPage
              title="Secretary Events"
              subtitle="Master Admin - Teaching event oversight"
              note="Cross-posting secretary event review is pending backend endpoint support. This page does not display synthetic event data."
            />
          }
        />
        <Route
          path="/admin/submissions"
          element={
            <AdminPlaceholderPage
              title="Resident Submissions"
              subtitle="Master Admin - Attendance submission oversight"
              note="Resident submission review is pending backend endpoint support. This page does not display synthetic attendance data."
            />
          }
        />
        <Route
          path="/pc/upload-ttf"
          element={
            <StubPage
              title="Programme PC Upload TTF"
              subtitle="Optional stub route for role switcher preview."
            />
          }
        />
        <Route path="/secretary" element={<Navigate to="/secretary/events" replace />} />
        <Route path="/secretary/events" element={<SecretaryTeachingSchedulePage />} />
        <Route path="/resident" element={<Navigate to="/resident/submissions" replace />} />
        <Route path="/resident/submissions" element={<ResidentSubmissionPage />} />
        <Route
          path="/external"
          element={
            <StubPage
              title="External Resident Portal"
              subtitle="Optional visual stub. External resident implementation is deferred."
            />
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  )
}

export default App



