import assert from 'node:assert/strict'
import test from 'node:test'

import { countStaffEnvelopeOverlaps } from './teachingEventOverlapWarning.ts'

const existing = [
  {
    id: 'event-a',
    postingCode: 'POSTING-A',
    eventDate: '2026-08-10',
    startTime: '10:00:00',
    endTime: '12:00:00',
    durationHours: 2,
  },
]

test('counts a direct overlap but does not treat touching endpoints as overlapping', () => {
  assert.equal(countStaffEnvelopeOverlaps(existing, {
    postingCode: 'POSTING-A',
    eventDate: '2026-08-10',
    startTime: '11:30',
    durationHours: 1,
  }), 1)
  assert.equal(countStaffEnvelopeOverlaps(existing, {
    postingCode: 'POSTING-A',
    eventDate: '2026-08-10',
    startTime: '12:00',
    durationHours: 1,
  }), 0)
})

test('limits warnings to the selected posting and excludes the event being edited', () => {
  assert.equal(countStaffEnvelopeOverlaps(existing, {
    postingCode: 'POSTING-B',
    eventDate: '2026-08-10',
    startTime: '11:30',
    durationHours: 1,
  }), 0)
  assert.equal(countStaffEnvelopeOverlaps(existing, {
    postingCode: 'POSTING-A',
    eventDate: '2026-08-10',
    startTime: '11:30',
    durationHours: 1,
    excludedEventId: 'event-a',
  }), 0)
})

test('detects overlaps across midnight', () => {
  assert.equal(countStaffEnvelopeOverlaps([
    {
      id: 'overnight',
      postingCode: 'POSTING-A',
      eventDate: '2026-08-10',
      startTime: '23:30',
      endTime: '00:30',
    },
  ], {
    postingCode: 'POSTING-A',
    eventDate: '2026-08-11',
    startTime: '00:15',
    durationHours: 1,
  }), 1)
})
