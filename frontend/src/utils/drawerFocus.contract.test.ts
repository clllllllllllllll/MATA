import assert from 'node:assert/strict'
import test from 'node:test'

import { focusTrapTargetIndex } from './drawerFocus.ts'

test('modal focus cycles from the last drawer control to the first', () => {
  assert.equal(focusTrapTargetIndex(2, 3, false), 0)
  assert.equal(focusTrapTargetIndex(1, 3, false), null)
})

test('modal focus cycles backwards from the first drawer control to the last', () => {
  assert.equal(focusTrapTargetIndex(0, 3, true), 2)
  assert.equal(focusTrapTargetIndex(1, 3, true), null)
})

test('modal focus returns into the drawer when focus starts outside it', () => {
  assert.equal(focusTrapTargetIndex(-1, 3, false), 0)
  assert.equal(focusTrapTargetIndex(-1, 3, true), 2)
  assert.equal(focusTrapTargetIndex(-1, 0, false), null)
})
