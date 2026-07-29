import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App from './App.tsx'
import { clearKnownLegacyBrowserCredentials } from './api/legacyAuthStorage.ts'
import { AppStateProvider } from './context/AppContext.tsx'
import { AuthProvider } from './context/AuthContext.tsx'
import './index.css'

clearKnownLegacyBrowserCredentials()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AppStateProvider>
        <AuthProvider>
          <App />
        </AuthProvider>
      </AppStateProvider>
    </BrowserRouter>
  </StrictMode>,
)
