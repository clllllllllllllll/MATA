import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
import { AdminHomePage } from './pages/admin/AdminHomePage'
import { AdminMultiPostingPage } from './pages/admin/AdminMultiPostingPage'
import { AdminUploadPage } from './pages/admin/AdminUploadPage'
import { AdminWarningsPage } from './pages/admin/AdminWarningsPage'
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
          element={
            <StubPage
              title="Secretary Dashboard"
              subtitle="Optional visual stub. Backend secretary integration is deferred."
            />
          }
        />
        <Route
          path="/resident"
          element={
            <StubPage
              title="Native Resident Portal"
              subtitle="Optional visual stub. Resident flow backend integration is deferred."
            />
          }
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
