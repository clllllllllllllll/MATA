import assert from 'node:assert/strict'
import test from 'node:test'

import { resolveTeachingNameLifecycleConflict } from './secretaryTeachingNameLifecycle.ts'
import { createScopedRequestFence } from './scopedRequestFence.ts'

test('the management-list request fence keeps only the newest same-scope response', () => {
  const fence = createScopedRequestFence()
  const first = fence.begin('GERI:period-1:active::0')
  const refresh = fence.begin('GERI:period-1:active::0')

  assert.equal(fence.isCurrent(first, 'GERI:period-1:active::0'), false)
  assert.equal(fence.isCurrent(refresh, 'GERI:period-1:active::0'), true)
})

test('the schedule-options request fence rejects stale same-scope and cross-scope responses', () => {
  const fence = createScopedRequestFence()
  const original = fence.begin('period-1:GERI')
  const retry = fence.begin('period-1:GERI')
  const changedProgramme = fence.begin('period-1:CARD')

  assert.equal(fence.isCurrent(original, 'period-1:GERI'), false)
  assert.equal(fence.isCurrent(retry, 'period-1:GERI'), false)
  assert.equal(fence.isCurrent(changedProgramme, 'period-1:CARD'), true)

  fence.invalidate()
  assert.equal(fence.isCurrent(changedProgramme, 'period-1:CARD'), false)
})

test('Teaching Name lifecycle conflicts retain their controlled recovery instructions', () => {
  assert.deepEqual(
    resolveTeachingNameLifecycleConflict({
      message: 'Teaching Name changed; refresh and retry',
      status: 409,
    }),
    {
      message: 'This Teaching Name was changed by someone else. Refresh the list and retry.',
      needsRefresh: true,
    },
  )
  assert.deepEqual(
    resolveTeachingNameLifecycleConflict({
      message: 'Teaching Name already exists',
      status: 409,
    }),
    {
      message: 'A Teaching Name with this name already exists in the selected programme and reporting period.',
      needsRefresh: false,
    },
  )
  assert.deepEqual(
    resolveTeachingNameLifecycleConflict({
      message: 'Teaching Name is in use',
      status: 409,
    }),
    {
      message: 'This Teaching Name is in use and cannot be deleted. Deactivate it instead.',
      needsRefresh: true,
    },
  )
})
