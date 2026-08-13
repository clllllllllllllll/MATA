import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(new URL('./AdminHomePage.tsx', import.meta.url), 'utf8')

test('Master home greeting uses the authenticated identity name', () => {
  assert.match(source, /const \{ identity \} = useAuth\(\)/)
  assert.match(source, /title=\{`Welcome back, \$\{identity\?\.name \?\? 'Master Admin'\}`\}/)
  assert.doesNotMatch(source, /Welcome back, Demo Admin/)
})
