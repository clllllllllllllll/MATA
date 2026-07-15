import {
  loadSecretaryEventsForPeriod,
  secretaryEventDateRange,
  shouldApplySecretaryEventLoad,
} from './secretaryEventPeriodScope.ts'
import type { ReportingPeriodOption } from '../types/upload.ts'

const assertEqual = <T,>(actual: T, expected: T, label: string) => {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${String(expected)}, received ${String(actual)}`)
  }
}

const period: ReportingPeriodOption = {
  id: 'current',
  label: 'Current',
  startDate: '2026-07-01',
  endDate: '2026-12-31',
  status: 'active',
}

const scopedCalls: Array<{ dateFrom?: string; dateTo?: string }> = []
const emptyEvents = (await loadSecretaryEventsForPeriod(period, async (range) => {
  scopedCalls.push(range)
  return [] as string[]
})) ?? []
assertEqual(emptyEvents.length, 0, 'empty scoped result remains empty')
assertEqual(scopedCalls.length, 1, 'empty scoped result makes exactly one request')
assertEqual(scopedCalls[0].dateFrom, period.startDate, 'scoped request keeps period start')
assertEqual(scopedCalls[0].dateTo, period.endDate, 'scoped request keeps period end')

const eventCalls: Array<{ dateFrom?: string; dateTo?: string }> = []
const events = (await loadSecretaryEventsForPeriod(period, async (range) => {
  eventCalls.push(range)
  return ['event']
})) ?? []
assertEqual(events.length, 1, 'scoped event response is returned normally')
assertEqual(eventCalls.length, 1, 'scoped event response makes one request')

const noPeriodCalls: Array<{ dateFrom?: string; dateTo?: string }> = []
const noPeriodEvents = await loadSecretaryEventsForPeriod(undefined, async (range) => {
  noPeriodCalls.push(range)
  return [] as string[]
})
assertEqual(noPeriodEvents, undefined, 'no selected period returns no request result')
assertEqual(noPeriodCalls.length, 0, 'no selected period makes zero event requests')
assertEqual(secretaryEventDateRange(undefined), undefined, 'no selected period has no request range')

assertEqual(
  shouldApplySecretaryEventLoad('current', 'next'),
  false,
  'a stale response cannot replace events after period selection changes',
)
assertEqual(
  shouldApplySecretaryEventLoad('current', null),
  false,
  'a stale response cannot replace the safe no-period state',
)
assertEqual(
  shouldApplySecretaryEventLoad('current', 'current'),
  true,
  'the selected period applies its own scoped response',
)
