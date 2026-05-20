import { useMemo, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { DetailDrawer } from '../../components/DetailDrawer'
import { PageHero } from '../../components/PageHero'
import type { NormalizedWarning } from '../../types/upload'
import { loadWarningContext } from '../../utils/storage'

type RuleTab = 'main_posting' | 'combine' | 'half_month'

const tabLabel: Record<RuleTab, string> = {
  main_posting: 'Main Posting',
  combine: 'To Combine Posting',
  half_month: 'Half Month Posting',
}

interface DemoRuleRow {
  programmeCode: string
  postingCode1: string
  postingCode2: string
  output: string
  note: string
}

const demoRows: Record<RuleTab, DemoRuleRow[]> = {
  main_posting: [
    {
      programmeCode: 'FM',
      postingCode1: 'TTSHFM',
      postingCode2: '-',
      output: 'NHGPlyNHGPly',
      note: 'Fallback exclusion posting for zero-match trigger cells.',
    },
    {
      programmeCode: 'FM',
      postingCode1: 'NHGFM-1',
      postingCode2: '-',
      output: 'TTSHFM',
      note: 'Recognised trigger posting.',
    },
  ],
  combine: [
    {
      programmeCode: 'GRM',
      postingCode1: 'Demo Posting A',
      postingCode2: 'Demo Posting B',
      output: 'Demo Combined Posting',
      note: 'Synthetic placeholder row for demo table state.',
    },
  ],
  half_month: [
    {
      programmeCode: 'REH',
      postingCode1: 'TTSHRehab',
      postingCode2: 'Demo Posting',
      output: '0.5 + 0.5 month weights',
      note: 'Synthetic split rule preview.',
    },
  ],
}

export const AdminMultiPostingPage = () => {
  const location = useLocation()
  const [activeTab, setActiveTab] = useState<RuleTab>('main_posting')
  const [isDrawerOpen, setDrawerOpen] = useState(false)
  const [saveMessage, setSaveMessage] = useState('')

  const warningContext = useMemo<NormalizedWarning | null>(() => {
    const stored = loadWarningContext()
    if (!stored) {
      return null
    }
    if ('warningId' in (location.state ?? {})) {
      return stored
    }
    return stored.type === 'unmatched_multi_posting' ? stored : null
  }, [location.state])

  return (
    <div className="page">
      <PageHero
        title="Multi-Posting Rules"
        subtitle="Master Admin - Configuration"
        actions={
          <button type="button" className="button button-primary" onClick={() => setDrawerOpen(true)}>
            Add rule
          </button>
        }
      />

      <section className="inline-callout callout-info">
        Changes apply on the next RDB re-upload. Existing resident postings are not mutated immediately.
      </section>

      {warningContext ? (
        <section className="inline-callout callout-warning">
          Resolving warning context: {warningContext.type} -{' '}
          {warningContext.residentName ?? 'Resident'} - {warningContext.mcr ?? 'M00000X'} -{' '}
          {warningContext.monthLabel ?? 'Unknown month'}
        </section>
      ) : null}

      <section className="card">
        <div className="tabs-underline tab-row">
          {(Object.keys(tabLabel) as RuleTab[]).map((tab) => (
            <button
              key={tab}
              type="button"
              className={`tab-button ${activeTab === tab ? 'is-active' : ''}`}
              onClick={() => setActiveTab(tab)}
            >
              {tabLabel[tab]}
            </button>
          ))}
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Programme</th>
                <th>Posting #1</th>
                <th>Posting #2</th>
                <th>Output</th>
                <th>Notes</th>
              </tr>
            </thead>
            <tbody>
              {demoRows[activeTab].map((row, index) => (
                <tr key={`${row.programmeCode}-${index}`}>
                  <td>{row.programmeCode}</td>
                  <td>{row.postingCode1}</td>
                  <td>{row.postingCode2}</td>
                  <td>{row.output}</td>
                  <td>{row.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {saveMessage ? <section className="inline-callout callout-success">{saveMessage}</section> : null}

      <DetailDrawer
        title="Add / Edit Multi-Posting Rule"
        open={isDrawerOpen}
        onClose={() => setDrawerOpen(false)}
        footer={
          <>
            <button type="button" className="button button-ghost" onClick={() => setDrawerOpen(false)}>
              Cancel
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={() => {
                setSaveMessage('Demo save complete. Backend CRUD wiring is deferred in this phase.')
                setDrawerOpen(false)
              }}
            >
              {warningContext ? 'Save & resolve warning' : 'Save'}
            </button>
          </>
        }
      >
        <div className="form-grid">
          <label>
            Programme code
            <input type="text" defaultValue={warningContext?.programmeCode ?? 'GRM'} />
          </label>
          <label>
            Rule type
            <select defaultValue={activeTab}>
              <option value="main_posting">main_posting</option>
              <option value="combine">combine</option>
              <option value="half_month">half_month</option>
            </select>
          </label>
          <label>
            Posting code #1
            <input type="text" defaultValue="Demo Posting A" />
          </label>
          <label>
            Posting code #2
            <input type="text" defaultValue="Demo Posting B" />
          </label>
          <label>
            Output value
            <input type="text" defaultValue="Demo Combined Posting" />
          </label>
        </div>
      </DetailDrawer>
    </div>
  )
}
