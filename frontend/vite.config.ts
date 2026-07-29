import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { validateFrontendEnvironment } from './src/config/frontendEnvironment'

const projectRoot = fileURLToPath(new URL('.', import.meta.url))

// https://vite.dev/config/
export default defineConfig(({ command, mode }) => {
  if (command === 'build') {
    const environment = loadEnv(mode, projectRoot, '')
    validateFrontendEnvironment(
      {
        appEnv: environment.VITE_APP_ENV,
        authMode: environment.VITE_AUTH_MODE,
        apiBaseUrl: environment.VITE_API_BASE_URL,
      },
      { requireExplicit: true },
    )
  }

  return {
    root: projectRoot,
    plugins: [react()],
    build: {
      sourcemap: false,
    },
  }
})
