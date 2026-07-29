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
        { appEnv, authMode },
        { requireExplicit: true },
      ),
      { appEnv, authMode },
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
        { appEnv, authMode },
        { requireExplicit: true },
      ),
    )
  }
})

test('development defaults remain local and stub when no build is running', () => {
  assert.deepEqual(validateFrontendEnvironment({}), {
    appEnv: 'local',
    authMode: 'stub',
  })
})

test('Vite validates the matrix at build time and deployment defaults are coherent', () => {
  const viteConfig = read('../../vite.config.ts')
  const dockerfile = read('../../Dockerfile')
  const compose = read('../../../docker-compose.yml')
  const workflow = read('../../../.github/workflows/production-security.yml')

  assert.match(viteConfig, /command === 'build'/)
  assert.match(viteConfig, /validateFrontendEnvironment/)
  assert.match(viteConfig, /requireExplicit: true/)
  assert.match(dockerfile, /ARG VITE_APP_ENV=local/)
  assert.match(dockerfile, /ARG VITE_AUTH_MODE=stub/)
  assert.match(compose, /VITE_APP_ENV: \$\{VITE_APP_ENV:-local\}/)
  assert.match(compose, /VITE_AUTH_MODE: \$\{VITE_AUTH_MODE:-stub\}/)
  assert.match(workflow, /VITE_APP_ENV: production/)
  assert.match(workflow, /VITE_AUTH_MODE: supabase/)
})
