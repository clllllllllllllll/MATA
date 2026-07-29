/// <reference types="node" />

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { validateFrontendEnvironment } from './frontendEnvironment.ts'

const read = (relativePath: string) =>
  readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), 'utf8')

test('the explicit frontend environment matrix permits only approved combinations', () => {
  for (const [appEnv, authMode] of [
    ['local', 'stub'],
    ['preview', 'demo'],
    ['preview', 'supabase'],
    ['production', 'supabase'],
  ] as const) {
    assert.deepEqual(
      validateFrontendEnvironment(
        { appEnv, authMode, apiBaseUrl: '/api/v1' },
        { requireExplicit: true },
      ),
      { appEnv, authMode, apiBaseUrl: '/api/v1' },
    )
  }

  for (const [appEnv, authMode] of [
    [undefined, 'stub'],
    ['local', undefined],
    ['unknown', 'stub'],
    ['local', 'unknown'],
    ['local', 'demo'],
    ['local', 'supabase'],
    ['preview', 'stub'],
    ['production', 'stub'],
    ['production', 'demo'],
  ] as const) {
    assert.throws(() =>
      validateFrontendEnvironment(
        { appEnv, authMode, apiBaseUrl: '/api/v1' },
        { requireExplicit: true },
      ),
    )
  }
})

test('development defaults remain local and stub when no build is running', () => {
  assert.deepEqual(validateFrontendEnvironment({}), {
    appEnv: 'local',
    authMode: 'stub',
    apiBaseUrl: '/api/v1',
  })
})

test('production and Supabase builds require the exact same-origin API base', () => {
  assert.deepEqual(
    validateFrontendEnvironment(
      {
        appEnv: 'production',
        authMode: 'supabase',
        apiBaseUrl: '/api/v1',
      },
      { requireExplicit: true },
    ),
    {
      appEnv: 'production',
      authMode: 'supabase',
      apiBaseUrl: '/api/v1',
    },
  )

  for (const apiBaseUrl of [
    undefined,
    '',
    '/api',
    '/api/v1/',
    '/unrelated/api/v1',
    'http://mata-backend.vercel.app/api/v1',
    'https://mata-backend.vercel.app/api/v1',
    'https://user:password@mata-backend.vercel.app/api/v1',
    '//mata-backend.vercel.app/api/v1',
  ]) {
    assert.throws(() =>
      validateFrontendEnvironment(
        {
          appEnv: 'production',
          authMode: 'supabase',
          apiBaseUrl,
        },
        { requireExplicit: true },
      ),
    )
  }

  assert.throws(() =>
    validateFrontendEnvironment(
      {
        appEnv: 'preview',
        authMode: 'supabase',
        apiBaseUrl: 'https://preview-backend.example.invalid/api/v1',
      },
      { requireExplicit: true },
    ),
  )
})

test('Vite validates every production variable and disables source maps', () => {
  const viteConfig = read('../../vite.config.ts')
  const dockerfile = read('../../Dockerfile')
  const compose = read('../../../docker-compose.yml')
  const workflow = read('../../../.github/workflows/production-security.yml')

  assert.match(viteConfig, /command === 'build'/)
  assert.match(viteConfig, /validateFrontendEnvironment/)
  assert.match(viteConfig, /requireExplicit: true/)
  assert.match(viteConfig, /apiBaseUrl: environment\.VITE_API_BASE_URL/)
  assert.match(viteConfig, /sourcemap: false/)
  const frontendConfig = read('./frontendConfig.ts')
  assert.match(
    frontendConfig,
    /import\.meta\.env\.DEV \? 'http:\/\/localhost:8000\/api\/v1' : undefined/,
  )
  assert.match(dockerfile, /ARG VITE_APP_ENV=local/)
  assert.match(dockerfile, /ARG VITE_AUTH_MODE=stub/)
  assert.match(dockerfile, /ARG VITE_API_BASE_URL=\/api\/v1/)
  assert.match(compose, /VITE_APP_ENV: \$\{VITE_APP_ENV:-local\}/)
  assert.match(compose, /VITE_AUTH_MODE: \$\{VITE_AUTH_MODE:-stub\}/)
  assert.match(compose, /VITE_API_BASE_URL: \$\{VITE_API_BASE_URL:-\/api\/v1\}/)
  assert.match(workflow, /VITE_APP_ENV: production/)
  assert.match(workflow, /VITE_AUTH_MODE: supabase/)
  assert.match(workflow, /VITE_API_BASE_URL: \/api\/v1/)
})
