import { Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'
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

function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/admin" replace />} />
      <Route element={<AppShell />}>
        <Route path="/admin" element={<AdminHomePage />} />
        <Route path="/admin/upload" element={<AdminUploadPage />} />
        <Route path="/admin/upload/warnings" element={<AdminWarningsPage />} />
        <Route path="/admin/config" element={<AdminConfigPage configViewRole="master_admin" />} />
        <Route path="/admin/config/multi" element={<AdminMultiPostingPage />} />
        <Route path="/admin/logs" element={<AdminLogsPage />} />
        <Route path="/admin/upload-logs" element={<AdminUploadLogsPage />} />
        <Route path="/admin/parsed-data" element={<AdminParsedDataPage />} />
        <Route path="/admin/secretary-events" element={<AdminSecretaryEventsPage />} />
        <Route path="/admin/submissions" element={<AdminResidentSubmissionsPage />} />
        <Route path="/pc/upload-ttf" element={<PcUploadTtfPage />} />
        <Route path="/pc/teaching-events" element={<PcTeachingEventsPage />} />
        <Route path="/pc/config" element={<AdminConfigPage configViewRole="programme_pc" />} />
        <Route path="/pc/warnings" element={<AdminWarningsPage />} />
        <Route path="/secretary" element={<Navigate to="/secretary/events" replace />} />
        <Route path="/secretary/events" element={<SecretaryTeachingSchedulePage />} />
        <Route path="/resident" element={<Navigate to="/resident/submissions" replace />} />
        <Route path="/resident/submissions" element={<ResidentSubmissionPage />} />
        <Route path="/resident/attendance" element={<ResidentAttendancePage />} />
        <Route
          path="/external"
          element={
            <StubPage
              title="Non-NHG Resident Portal"
              subtitle="Optional visual stub. Non-NHG Resident implementation is deferred."
              variant="non_nhg"
            />
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/admin" replace />} />
    </Routes>
  )
}

export default App



