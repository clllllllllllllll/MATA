import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { IconChevRight, NamedIcon } from '../../components/icons'
import { PageHero } from '../../components/PageHero'

type ConfigSectionKey =
  | 'reporting-periods'
  | 'public-holidays'
  | 'programmes'
  | 'loa-types'
  | 'multi-posting-rules'
  | 'posting-groups'
  | 'weekend-exceptions'
  | 'global-session-types'

interface ConfigSection {
  key: ConfigSectionKey
  label: string
  icon: string
  status: string
  title: string
  description: string
  stateLabel: string
  nextStep: string
  rows: Array<{
    field: string
    current: string
    next: string
    mono?: boolean
  }>
  actionLabel?: string
  actionPath?: string
}

const configSections: ConfigSection[] = [
  {
    key: 'reporting-periods',
    label: 'Reporting Periods',
    icon: 'calendar',
    status: 'Pending',
    title: 'Reporting Periods',
    description: 'Reporting periods are required before RDB, TTF, and FormF1 uploads can be safely scoped.',
    stateLabel: 'CRUD pending',
    nextStep:
      'CRUD wiring is planned for a later task. Delete should eventually be blocked when referenced by uploads, postings, targets, or FormF1 records.',
    rows: [
      {
        field: 'Upload dependency',
        current: 'RDB, TTF, and FormF1 uploads require a reporting period.',
        next: 'Add create/edit/list controls after the backend workflow is ready.',
      },
      {
        field: 'Delete guard',
        current: 'No delete action is exposed in this shell.',
        next: 'Block deletion when referenced by upload_logs, resident_postings, teaching_targets, or form_f1_records.',
      },
      {
        field: 'Current mode',
        current: 'Read-only placeholder.',
        next: 'CRUD pending.',
      },
    ],
  },
  {
    key: 'public-holidays',
    label: 'Public Holidays',
    icon: 'calendar',
    status: 'Upload',
    title: 'Public Holidays',
    description: 'Holiday and AY boundary data is currently upload-driven from the Academic Calendar / Public Holiday workbook.',
    stateLabel: 'Upload-driven data; manual CRUD pending',
    nextStep:
      'Manual CRUD can be added later. MOM/public holiday sync is intentionally not implemented in this task.',
    rows: [
      {
        field: 'Source',
        current: 'Academic Calendar / Public Holiday workbook upload.',
        next: 'Keep manual edits behind a future CRUD task.',
      },
      {
        field: 'Runtime use',
        current: 'Public holidays block secretary and resident ad-hoc event creation server-side.',
        next: 'Expose read/edit controls only after endpoint scope is confirmed.',
      },
      {
        field: 'External sync',
        current: 'No MOM sync in this shell.',
        next: 'Do not add sync behavior here.',
      },
    ],
  },
  {
    key: 'programmes',
    label: 'Programmes',
    icon: 'database',
    status: 'Seeded',
    title: 'Programmes',
    description: 'Programme definitions are seeded in the database and later CRUD-manageable.',
    stateLabel: 'Read-only preview pending',
    nextStep: 'Future CRUD should preserve programme scope and source-of-truth rules before edits are enabled.',
    rows: [
      {
        field: 'Seed source',
        current: 'Programme catalogue is database-seeded.',
        next: 'Add safe edit controls for aliases, r-year behavior, and AY categories later.',
      },
      {
        field: 'Scope',
        current: 'Admin accounts are programme-scoped.',
        next: 'Server-side scope checks must remain authoritative.',
      },
      {
        field: 'Current mode',
        current: 'No programme rows are displayed here yet.',
        next: 'Read-only preview pending.',
      },
    ],
  },
  {
    key: 'loa-types',
    label: 'LOA Types',
    icon: 'file',
    status: 'Seeded',
    title: 'LOA Types',
    description: 'LOA types are seeded and later CRUD-manageable.',
    stateLabel: 'CRUD wiring pending',
    nextStep: 'Expose maintenance controls only after validation and audit rules are confirmed.',
    rows: [
      {
        field: 'Seeded list',
        current: 'Confirmed LOA types are seeded for parser/audit display.',
        next: 'Manual CRUD pending.',
      },
      {
        field: 'Parser behavior',
        current: 'Unknown LOA values should warn rather than reject uploads.',
        next: 'Keep parser behavior unchanged in this UI task.',
      },
      {
        field: 'Compliance',
        current: 'Compliance denominator remains governed by FormF1 active/inactive status.',
        next: 'Do not add compliance logic here.',
      },
    ],
  },
  {
    key: 'multi-posting-rules',
    label: 'Multi-Posting Rules',
    icon: 'settings',
    status: 'Linked',
    title: 'Multi-Posting Rules',
    description: 'Rules are seeded and managed through the dedicated Multi-Posting Rules page.',
    stateLabel: 'Manage via dedicated Multi-Posting Rules page',
    nextStep:
      'Warning re-evaluation is a future backend task and is not implemented in this shell.',
    actionLabel: 'Open Multi-Posting Rules',
    actionPath: '/admin/config/multi',
    rows: [
      {
        field: 'Dedicated page',
        current: '/admin/config/multi',
        next: 'Open the existing deep-link page for the current multi-posting workflow.',
        mono: true,
      },
      {
        field: 'Parser impact',
        current: 'Rules apply when RDB parsing resolves combined or split posting cells.',
        next: 'Changes should apply on next RDB re-upload.',
      },
      {
        field: 'Warning handling',
        current: 'This shell does not re-evaluate existing warnings.',
        next: 'Backend warning re-evaluation remains future work.',
      },
    ],
  },
  {
    key: 'posting-groups',
    label: 'Posting Groups',
    icon: 'grid',
    status: 'Pending',
    title: 'Posting Groups',
    description: 'Posting groups pool related posting codes for compliance aggregation and are separate from multi-posting rules.',
    stateLabel: 'Manual CRUD wiring pending',
    nextStep:
      'Groups are seeded from TTF Column E. Manual CRUD should keep grouped posting aggregation distinct from multi-posting parse rules.',
    rows: [
      {
        field: 'Use case',
        current: 'Pool related posting codes so compliance can aggregate across a group.',
        next: 'Expose group maintenance after CRUD endpoints and validation are ready.',
      },
      {
        field: 'Seed source',
        current: 'Seeded from non-empty TTF Column E values.',
        next: 'Keep upload seeding behavior unchanged.',
      },
      {
        field: 'Not the same as',
        current: 'Multi-posting rules.',
        next: 'Use multi-posting rules for RDB cell collapse/split behavior, not group aggregation.',
      },
    ],
  },
  {
    key: 'weekend-exceptions',
    label: 'Weekend Exceptions',
    icon: 'calendar',
    status: 'Seeded',
    title: 'Weekend Exceptions',
    description: 'Weekend exceptions are seeded and later CRUD-manageable.',
    stateLabel: 'CRUD wiring pending',
    nextStep: 'Future edits should preserve read-time exception behavior and confirmed programme-specific rules.',
    rows: [
      {
        field: 'Current source',
        current: 'Seeded weekend exception configuration.',
        next: 'Manual CRUD pending.',
      },
      {
        field: 'Compliance use',
        current: 'Exceptions decide whether weekend sessions count, including read-time ORTHO mutation.',
        next: 'Do not mutate raw attendance records.',
      },
      {
        field: 'Current mode',
        current: 'No editable rows exposed here.',
        next: 'CRUD wiring pending.',
      },
    ],
  },
  {
    key: 'global-session-types',
    label: 'Global Session Types',
    icon: 'settings',
    status: 'Pending',
    title: 'Global Session Types',
    description: 'Global session types are compliance-exempt teaching names and later CRUD-manageable.',
    stateLabel: 'CRUD wiring pending',
    nextStep:
      'Future CRUD should keep active global names available to secretary/resident dropdowns while excluding them from compliance.',
    rows: [
      {
        field: 'Compliance effect',
        current: 'Matching global session types are excluded from both numerator and denominator.',
        next: 'Keep this exclusion server-side.',
      },
      {
        field: 'Dropdown use',
        current: 'Secretary and resident ad-hoc flows can include global teaching names when wired.',
        next: 'Manual CRUD pending.',
      },
      {
        field: 'Current mode',
        current: 'Read-only placeholder.',
        next: 'CRUD wiring pending.',
      },
    ],
  },
]

export const AdminConfigPage = () => {
  const navigate = useNavigate()
  const [activeSectionKey, setActiveSectionKey] = useState<ConfigSectionKey>('reporting-periods')
  const activeSection =
    configSections.find((section) => section.key === activeSectionKey) ?? configSections[0]

  return (
    <div className="page admin-config-page">
      <PageHero title="Configuration" subtitle="Master Admin - All programmes" />

      <section className="admin-config-shell" aria-label="Configuration sections">
        <nav className="admin-config-nav-card" aria-label="Configuration navigation">
          {configSections.map((section) => {
            const isActive = section.key === activeSection.key
            return (
              <button
                key={section.key}
                type="button"
                className={`admin-config-nav-item ${isActive ? 'is-active' : ''}`}
                onClick={() => setActiveSectionKey(section.key)}
                aria-current={isActive ? 'page' : undefined}
              >
                <span className="admin-config-nav-main">
                  <NamedIcon name={section.icon} size={14} />
                  <span>{section.label}</span>
                </span>
                <span className="admin-config-nav-chip">{section.status}</span>
              </button>
            )
          })}
        </nav>

        <article className="card admin-config-content-card">
          <header className="admin-config-content-header">
            <div>
              <div className="admin-config-title-row">
                <h2>{activeSection.title}</h2>
                <span className="admin-config-status-chip">{activeSection.stateLabel}</span>
              </div>
              <p>{activeSection.description}</p>
            </div>
            {activeSection.actionLabel && activeSection.actionPath ? (
              <button
                type="button"
                className="button button-primary"
                onClick={() => navigate(activeSection.actionPath ?? '/admin/config/multi')}
              >
                {activeSection.actionLabel}
                <IconChevRight size={14} />
              </button>
            ) : null}
          </header>

          <div className="admin-config-callout">
            <strong>Next step</strong>
            <span>{activeSection.nextStep}</span>
          </div>

          <div className="admin-config-table-wrap">
            <table className="admin-config-table">
              <thead>
                <tr>
                  <th>Area</th>
                  <th>Current treatment</th>
                  <th>Planned follow-up</th>
                </tr>
              </thead>
              <tbody>
                {activeSection.rows.map((row) => (
                  <tr key={row.field}>
                    <td className={row.mono ? 'mono' : undefined}>{row.field}</td>
                    <td className={row.mono ? 'mono' : undefined}>{row.current}</td>
                    <td>{row.next}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </article>
      </section>
    </div>
  )
}

