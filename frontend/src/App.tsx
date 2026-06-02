import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { AdminHomePage } from './pages/admin/AdminHomePage'
import { AdminMultiPostingPage } from './pages/admin/AdminMultiPostingPage'
import { AdminUploadPage } from './pages/admin/AdminUploadPage'
import { AdminWarningsPage } from './pages/admin/AdminWarningsPage'
import { ResidentSubmissionPage } from './pages/resident/ResidentSubmissionPage'
import { SecretaryTeachingSchedulePage } from './pages/secretary/SecretaryTeachingSchedulePage'
import { StubPage } from './pages/StubPage'

function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Navigate to="/admin" replace />} />
        <Route path="/admin" element={<AdminHomePage />} />
        <Route path="/admin/upload" element={<AdminUploadPage />} />
        <Route path="/admin/upload/warnings" element={<AdminWarningsPage />} />
        <Route path="/admin/config/multi" element={<AdminMultiPostingPage />} />
        <Route
          path="/pc/upload-ttf"
          element={
            <StubPage
              title="Programme PC Upload TTF"
              subtitle="Optional stub route for role switcher preview."
            />
          }
        />
        <Route
          path="/secretary"
          element={<Navigate to="/secretary/events" replace />}
        />
        <Route
          path="/secretary/events"
          element={<SecretaryTeachingSchedulePage />}
        />
        <Route
          path="/resident"
          element={<Navigate to="/resident/submissions" replace />}
        />
        <Route
          path="/resident/submissions"
          element={<ResidentSubmissionPage />}
        />
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
