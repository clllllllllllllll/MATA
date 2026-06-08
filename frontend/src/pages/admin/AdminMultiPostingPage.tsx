import { Fragment, type FormEvent, type ReactNode, useCallback, useEffect, useMemo, useState } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import {
  createMultiPostingRule,
  deleteMultiPostingRule,
  listMultiPostingRules,
  type MultiPostingRule,
  type MultiPostingRulePayload,
  type MultiPostingRuleType,
  updateMultiPostingRule,
} from '../../api/multiPostingRules'
import { listPostingCodes, type PostingCodeOption } from '../../api/postingCodes'
import { listProgrammes, type Programme } from '../../api/programmes'
import { ApiRequestError } from '../../api/http'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconPlus, IconRefresh } from '../../components/icons'
import { useAppState } from '../../context/useAppState'
import type { NormalizedWarning } from '../../types/upload'
import { loadWarningContext } from '../../utils/storage'

type RuleTab = MultiPostingRuleType
type ConfigViewRole = 'master_admin' | 'programme_pc'

interface MultiPostingFormState {
  programmeCode: string
  postingCode1: string
  postingCode2: string
  combinedLabel: string
  mainPostingCode: string
  exclusionCode: string
}

type Feedback = { tone: 'success' | 'error'; message: string; description?: string } | null

const ruleTabs: RuleTab[] = ['main_posting', 'combine', 'half_month']

const tabLabel: Record<RuleTab, string> = {
  main_posting: 'Main Posting',
  combine: 'To Combine Posting',
  half_month: 'Half Month Posting',
}

const outputColumnLabel: Record<RuleTab, string> = {
  main_posting: 'Main Posting',
  combine: 'Combined Posting',
  half_month: 'Half Month Posting',
}

const multiPostingTableColumnCount = 6

const drawerTitle: Record<RuleTab, { create: string; edit: string }> = {
  main_posting: {
    create: 'New Main Posting Rule',
    edit: 'Edit Main Posting Rule',
  },
  combine: {
    create: 'New Combine Rule',
    edit: 'Edit Combine Rule',
  },
  half_month: {
    create: 'New Half Month Rule',
    edit: 'Edit Half Month Rule',
  },
}

const emptyForm: MultiPostingFormState = {
  programmeCode: '',
  postingCode1: '',
  postingCode2: '',
  combinedLabel: '',
  mainPostingCode: '',
  exclusionCode: '',
}

const toProgrammeFallback = (code: string): Programme => ({
  id: code,
  code,
  name: '',
  ayDateCategory: '',
  rYearRequired: false,
  isSubspecialty: false,
})

const describeError = (error: unknown, fallback: string): string =>
  error instanceof ApiRequestError ? error.message : fallback

const formatDate = (value?: string): string => {
  if (!value) {
    return '-'
  }
  const date = new Date(value)
  if (Number.isNaN(date.valueOf())) {
    return '-'
  }
  return new Intl.DateTimeFormat('en-SG', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(date)
}

const programmeOptionLabel = (programme: Programme): string =>
  programme.name ? `${programme.code} - ${programme.name}` : programme.code

const postingOptionLabel = (postingCode: PostingCodeOption): string => {
  const display = postingCode.displayName ?? postingCode.department ?? postingCode.institution
  return display ? `${postingCode.code} - ${display}` : postingCode.code
}

const ProgrammeScopeText = ({ programmeCodes }: { programmeCodes: string[] }) => {
  if (programmeCodes.length === 0) {
    return <>Rules for your accessible programmes will appear here once created.</>
  }

  return (
    <>
      Rules for{' '}
      {programmeCodes.map((programmeCode, index) => (
        <Fragment key={programmeCode}>
          {index > 0 ? (index === programmeCodes.length - 1 ? ' and ' : ', ') : null}
          <strong>{programmeCode}</strong>
        </Fragment>
      ))}{' '}
      will appear here once created.
    </>
  )
}

const emptyBannerCopy = (
  activeTab: RuleTab,
  viewRole: ConfigViewRole,
  programmeCodes: string[],
): { title: string; body: ReactNode; hint: string } => {
  if (activeTab === 'combine') {
    return {
      title: viewRole === 'master_admin' ? 'No combined posting rules yet' : 'No combined posting rules for your programmes',
      body:
        viewRole === 'master_admin'
          ? 'Combined posting rules will appear here once created.'
          : 'Combined posting rules for your accessible programmes will appear here once created.',
      hint: 'Changes apply on the next RDB re-upload',
    }
  }

  if (activeTab === 'half_month') {
    return {
      title: viewRole === 'master_admin' ? 'No half month posting rules yet' : 'No half month posting rules for your programmes',
      body:
        viewRole === 'master_admin'
          ? 'Half month posting rules will appear here once created.'
          : 'Half month posting rules for your accessible programmes will appear here once created.',
      hint: 'Changes apply on the next RDB re-upload',
    }
  }

  return {
    title: viewRole === 'master_admin' ? 'No main posting rules yet' : 'No main posting rules for your programmes',
    body:
      viewRole === 'programme_pc' ? (
        <ProgrammeScopeText programmeCodes={programmeCodes} />
      ) : (
        'Rules will appear here once created.'
      ),
    hint: 'Changes apply on the next RDB re-upload',
  }
}

const EmptyBanner = ({
  title,
  body,
  hint,
}: {
  title: string
  body: ReactNode
  hint?: string
}) => (
  <div className="multi-posting-empty-banner-wrap">
    <div className="multi-posting-empty-banner">
      <div className="multi-posting-empty-banner-content">
        <div className="multi-posting-empty-banner-title">{title}</div>
        <div className="multi-posting-empty-banner-body">{body}</div>
        {hint ? (
          <div className="multi-posting-empty-banner-hint">
            <span aria-hidden="true">i</span>
            {hint}
          </div>
        ) : null}
      </div>
    </div>
  </div>
)

const MultiPostingEmptyRow = ({
  title,
  body,
  hint,
}: {
  title: string
  body: ReactNode
  hint?: string
}) => (
  <tr className="multi-posting-empty-row">
    <td className="multi-posting-empty-cell" colSpan={multiPostingTableColumnCount}>
      <EmptyBanner title={title} body={body} hint={hint} />
    </td>
  </tr>
)

interface MultiPostingRulesSectionProps {
  configViewRole?: ConfigViewRole
}

export const MultiPostingRulesSection = ({ configViewRole }: MultiPostingRulesSectionProps) => {
  const location = useLocation()
  const { demoAdminId, demoAdminProgrammes, role } = useAppState()
  const viewRole = configViewRole ?? (role === 'programme_pc' ? 'programme_pc' : 'master_admin')
  const adminLevel = role === 'master_admin' ? 'master' : 'programme'
  const [activeTab, setActiveTab] = useState<RuleTab>('main_posting')
  const [rules, setRules] = useState<MultiPostingRule[]>([])
  const [programmeOptions, setProgrammeOptions] = useState<Programme[]>([])
  const [postingCodeOptions, setPostingCodeOptions] = useState<PostingCodeOption[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerMode, setDrawerMode] = useState<'create' | 'edit'>('create')
  const [selectedRule, setSelectedRule] = useState<MultiPostingRule | null>(null)
  const [formState, setFormState] = useState<MultiPostingFormState>(emptyForm)
  const [submitState, setSubmitState] = useState<'idle' | 'submitting' | 'error'>('idle')
  const [feedback, setFeedback] = useState<Feedback>(null)
  const [confirmingDeleteRule, setConfirmingDeleteRule] = useState<MultiPostingRule | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

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

  const sortedProgrammeOptions = useMemo(
    () => {
      const byCode = new Map(programmeOptions.map((programme) => [programme.code, programme]))
      if (formState.programmeCode && !byCode.has(formState.programmeCode)) {
        byCode.set(formState.programmeCode, {
          ...toProgrammeFallback(formState.programmeCode),
          name: 'Current programme no longer exists',
        })
      }
      return Array.from(byCode.values()).sort((left, right) => left.code.localeCompare(right.code))
    },
    [formState.programmeCode, programmeOptions],
  )

  const sortedPostingCodeOptions = useMemo(
    () => {
      const byCode = new Map(postingCodeOptions.map((postingCode) => [postingCode.code, postingCode]))
      ;[
        formState.postingCode1,
        formState.postingCode2,
        formState.combinedLabel,
        formState.mainPostingCode,
        formState.exclusionCode,
      ].forEach((code) => {
        if (code && !byCode.has(code)) {
          byCode.set(code, {
            id: code,
            code,
            displayName: 'Current posting no longer exists',
          })
        }
      })
      return Array.from(byCode.values()).sort((left, right) => left.code.localeCompare(right.code))
    },
    [formState, postingCodeOptions],
  )

  const ruleRows = useMemo(
    () =>
      [...rules].sort(
        (left, right) =>
          left.programmeCode.localeCompare(right.programmeCode) ||
          left.postingCode1.localeCompare(right.postingCode1) ||
          (left.postingCode2 ?? '').localeCompare(right.postingCode2 ?? ''),
      ),
    [rules],
  )
  const emptyStateCopy = emptyBannerCopy(activeTab, viewRole, demoAdminProgrammes)

  const reloadRules = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [ruleRows, postingRows, programmeRows] = await Promise.all([
        listMultiPostingRules({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          ruleType: activeTab,
        }),
        listPostingCodes({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
        }),
        role === 'master_admin'
          ? listProgrammes({
              adminId: demoAdminId,
              adminProgrammes: demoAdminProgrammes,
              adminLevel,
            })
          : Promise.resolve(demoAdminProgrammes.map(toProgrammeFallback)),
      ])
      setRules(ruleRows)
      setPostingCodeOptions(postingRows)
      setProgrammeOptions(programmeRows)
    } catch (error) {
      setLoadError(describeError(error, 'Unable to load multi-posting rules.'))
      setRules([])
      setPostingCodeOptions([])
      setProgrammeOptions([])
    } finally {
      setLoading(false)
    }
  }, [activeTab, adminLevel, demoAdminId, demoAdminProgrammes, role])

  useEffect(() => {
    let cancelled = false
    queueMicrotask(() => {
      if (!cancelled) {
        void reloadRules()
      }
    })
    return () => {
      cancelled = true
    }
  }, [reloadRules])

  const openCreateDrawer = () => {
    setDrawerMode('create')
    setSelectedRule(null)
    setFormState({
      ...emptyForm,
      programmeCode: sortedProgrammeOptions[0]?.code ?? demoAdminProgrammes[0] ?? '',
    })
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteRule(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (rule: MultiPostingRule) => {
    setDrawerMode('edit')
    setSelectedRule(rule)
    setFormState({
      programmeCode: rule.programmeCode,
      postingCode1: rule.postingCode1,
      postingCode2: rule.postingCode2 ?? '',
      combinedLabel: rule.combinedLabel ?? '',
      mainPostingCode: rule.mainPostingCode ?? '',
      exclusionCode: rule.exclusionCode ?? '',
    })
    setSubmitState('idle')
    setFeedback(null)
    setConfirmingDeleteRule(null)
    setDrawerOpen(true)
  }

  const closeDrawer = () => {
    if (submitState === 'submitting') {
      return
    }
    setDrawerOpen(false)
    setSelectedRule(null)
    setFormState(emptyForm)
    setSubmitState('idle')
  }

  const setFormField = (field: keyof MultiPostingFormState, value: string) => {
    setFormState((current) => ({ ...current, [field]: value }))
    setSubmitState('idle')
  }

  const payloadFromForm = (): MultiPostingRulePayload => ({
    programmeCode: formState.programmeCode.trim(),
    postingCode1: formState.postingCode1.trim(),
    postingCode2: formState.postingCode2.trim() || null,
    ruleType: activeTab,
    combinedLabel: activeTab === 'combine' ? formState.combinedLabel.trim() || null : null,
    mainPostingCode: activeTab === 'main_posting' ? formState.mainPostingCode.trim() || null : null,
    exclusionCode: activeTab === 'main_posting' ? formState.exclusionCode.trim() || null : null,
  })

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitState('submitting')
    setFeedback(null)
    try {
      if (drawerMode === 'edit' && selectedRule) {
        await updateMultiPostingRule({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          id: selectedRule.id,
          payload: payloadFromForm(),
        })
        setFeedback({ tone: 'success', message: 'Multi-posting rule updated.' })
      } else {
        await createMultiPostingRule({
          adminId: demoAdminId,
          adminProgrammes: demoAdminProgrammes,
          adminLevel,
          payload: payloadFromForm(),
        })
        setFeedback({ tone: 'success', message: 'Multi-posting rule created.' })
      }
      await reloadRules()
      setDrawerOpen(false)
      setSelectedRule(null)
      setFormState(emptyForm)
      setSubmitState('idle')
    } catch (error) {
      setSubmitState('error')
      setFeedback({
        tone: 'error',
        message: describeError(error, 'Unable to save multi-posting rule.'),
        description: 'Check that the selected programme and posting codes are valid for this rule type.',
      })
    }
  }

  const handleDelete = async (rule: MultiPostingRule) => {
    setDeletingId(rule.id)
    setFeedback(null)
    try {
      await deleteMultiPostingRule({
        adminId: demoAdminId,
        adminProgrammes: demoAdminProgrammes,
        adminLevel,
        id: rule.id,
      })
      setFeedback({ tone: 'success', message: 'Multi-posting rule deleted.' })
      await reloadRules()
      setConfirmingDeleteRule(null)
    } catch (error) {
      setConfirmingDeleteRule(null)
      setFeedback({
        tone: 'error',
        message: describeError(error, 'Unable to delete multi-posting rule.'),
        description: 'Existing parsed posting rows are not changed by this configuration action.',
      })
    } finally {
      setDeletingId(null)
    }
  }

  const renderOutput = (rule: MultiPostingRule): ReactNode => {
    if (rule.ruleType === 'combine') {
      return rule.combinedLabel ?? '-'
    }
    if (rule.ruleType === 'half_month') {
      return '50/50 split'
    }
    return (
      <span className="multi-posting-output-stack">
        <span>{rule.mainPostingCode ?? '-'}</span>
        {rule.exclusionCode ? <small>Fallback: {rule.exclusionCode}</small> : null}
      </span>
    )
  }

  return (
    <>
      <header className="admin-config-content-header multi-posting-inline-header">
        <div>
          <div className="admin-config-title-row">
            <h2>Multi-Posting Rules</h2>
          </div>
          <p>Multi-Posting Rules affect RDB parsing. Posting Groups affect compliance aggregation.</p>
        </div>
        <div className="admin-config-actions multi-posting-header-actions">
          <button
            type="button"
            className="button button-secondary"
            onClick={() => void reloadRules()}
            disabled={loading}
          >
            <IconRefresh size={14} />
            Retry
          </button>
          <button type="button" className="button button-primary" onClick={openCreateDrawer}>
            <IconPlus size={14} />
            New Rule
          </button>
        </div>
      </header>

      {warningContext ? (
        <section className="inline-callout callout-warning">
          Resolving unmatched multi-posting warning:{' '}
          {warningContext.residentName ?? 'Resident'} - {warningContext.mcr ?? 'M00000X'} -{' '}
          {warningContext.monthLabel ?? 'Unknown month'}
        </section>
      ) : null}

      {feedback ? (
        <section
          className={`inline-callout ${feedback.tone === 'error' ? 'callout-error' : 'callout-success'} admin-config-feedback`}
          role="status"
        >
          <div className="admin-config-feedback-content">
            <strong>{feedback.message}</strong>
            {feedback.description ? <p>{feedback.description}</p> : null}
          </div>
          <button
            type="button"
            className="admin-config-feedback-dismiss"
            onClick={() => setFeedback(null)}
            aria-label="Dismiss feedback"
          >
            Dismiss
          </button>
        </section>
      ) : null}

      <section className="multi-posting-card">
        <div className="tabs-underline tab-row multi-posting-tabs" role="tablist" aria-label="Multi-posting rule type">
          {ruleTabs.map((tab) => (
            <button
              key={tab}
              type="button"
              className={`tab-button ${activeTab === tab ? 'is-active' : ''}`}
              onClick={() => {
                setActiveTab(tab)
                setFeedback(null)
                setConfirmingDeleteRule(null)
              }}
            >
              {tabLabel[tab]}
            </button>
          ))}
        </div>

        {loading ? (
          <div className="configuration-empty-note">Loading multi-posting rules...</div>
        ) : loadError ? (
          <div className="configuration-empty-note">
            <div>
              <h3>Unable to load multi-posting rules</h3>
              <p>{loadError}</p>
            </div>
          </div>
        ) : (
          <div className="admin-config-table-wrap">
            <table className="admin-config-table multi-posting-table">
              <thead>
                <tr>
                  <th>Programme</th>
                  <th>Posting 1</th>
                  <th>Posting 2</th>
                  <th>{outputColumnLabel[activeTab]}</th>
                  <th>Updated</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {ruleRows.length === 0 ? (
                  <MultiPostingEmptyRow
                    title={emptyStateCopy.title}
                    body={emptyStateCopy.body}
                    hint={emptyStateCopy.hint}
                  />
                ) : (
                  ruleRows.map((rule) => (
                    <tr key={rule.id}>
                      <td>{rule.programmeCode}</td>
                      <td title={rule.postingCode1}>{rule.postingCode1}</td>
                      <td title={rule.postingCode2 ?? 'No second posting'}>{rule.postingCode2 ?? '-'}</td>
                      <td title={rule.combinedLabel ?? rule.mainPostingCode ?? ''}>{renderOutput(rule)}</td>
                      <td>{formatDate(rule.updatedAt)}</td>
                      <td>
                        <div className="admin-config-row-actions">
                          <button type="button" className="button button-secondary" onClick={() => openEditDrawer(rule)}>
                            Edit
                          </button>
                            <button type="button" className="button button-ghost danger" onClick={() => setConfirmingDeleteRule(rule)}>
                              Delete
                            </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {confirmingDeleteRule ? (
        <section className="inline-callout callout-warning admin-config-feedback" role="status">
          <div className="admin-config-feedback-content">
            <strong>Delete multi-posting rule?</strong>
            <p>This affects future RDB parsing only. Existing parsed posting rows are not changed.</p>
          </div>
          <div className="admin-config-confirm-actions">
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setConfirmingDeleteRule(null)}
              disabled={deletingId === confirmingDeleteRule.id}
            >
              Cancel
            </button>
            <button
              type="button"
              className="button button-ghost danger"
              onClick={() => void handleDelete(confirmingDeleteRule)}
              disabled={deletingId === confirmingDeleteRule.id}
            >
              {deletingId === confirmingDeleteRule.id ? 'Deleting...' : 'Delete rule'}
            </button>
          </div>
        </section>
      ) : null}

      <DetailDrawer
        title={drawerMode === 'edit' ? drawerTitle[activeTab].edit : drawerTitle[activeTab].create}
        open={drawerOpen}
        onClose={closeDrawer}
        footer={
          <>
            <button type="button" className="button button-ghost" onClick={closeDrawer}>
              Cancel
            </button>
            <button type="submit" className="button button-primary" form="multi-posting-form" disabled={submitState === 'submitting'}>
              {submitState === 'submitting' ? 'Saving...' : 'Save Rule'}
            </button>
          </>
        }
      >
        <form id="multi-posting-form" className="form-grid" onSubmit={(event) => void handleSubmit(event)}>
          <div className="multi-posting-form-card">
            <label>
              Programme
              <select value={formState.programmeCode} onChange={(event) => setFormField('programmeCode', event.target.value)} required>
                <option value="" disabled>
                  Select programme
                </option>
                {sortedProgrammeOptions.map((programme) => (
                  <option key={programme.code} value={programme.code}>
                    {programmeOptionLabel(programme)}
                  </option>
                ))}
              </select>
            </label>

            <div className="multi-posting-form-group">
              <h3>When the RDB cell contains</h3>
              <label>
                Posting 1
                <select value={formState.postingCode1} onChange={(event) => setFormField('postingCode1', event.target.value)} required>
                  <option value="" disabled>
                    Select posting
                  </option>
                  {sortedPostingCodeOptions.map((postingCode) => (
                    <option key={postingCode.code} value={postingCode.code}>
                      {postingOptionLabel(postingCode)}
                    </option>
                  ))}
                </select>
              </label>

              <label>
                Posting 2{activeTab === 'main_posting' ? ', optional' : ''}
                <select
                  value={formState.postingCode2}
                  onChange={(event) => setFormField('postingCode2', event.target.value)}
                  required={activeTab !== 'main_posting'}
                >
                  <option value="">{activeTab === 'main_posting' ? 'No second posting' : 'Select posting'}</option>
                  {sortedPostingCodeOptions.map((postingCode) => (
                    <option key={postingCode.code} value={postingCode.code}>
                      {postingOptionLabel(postingCode)}
                    </option>
                  ))}
                </select>
                {activeTab === 'main_posting' ? (
                  <span className="admin-config-helper">
                    Leave Posting 2 blank when the rule applies to one posting only.
                  </span>
                ) : null}
              </label>
            </div>

            {activeTab === 'combine' ? (
              <div className="multi-posting-form-group">
                <h3>Save resident posting as</h3>
                <label className="multi-posting-field-wide">
                  Combined posting
                  <select value={formState.combinedLabel} onChange={(event) => setFormField('combinedLabel', event.target.value)} required>
                    <option value="" disabled>
                      Select combined posting
                    </option>
                    {sortedPostingCodeOptions.map((postingCode) => (
                      <option key={postingCode.code} value={postingCode.code}>
                        {postingOptionLabel(postingCode)}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="admin-config-helper">
                  The RDB parser stores this combined posting on the next RDB upload.
                </p>
              </div>
            ) : null}

            {activeTab === 'main_posting' ? (
              <div className="multi-posting-form-group">
                <h3>Save resident posting as</h3>
                <label>
                  Main posting
                  <select value={formState.mainPostingCode} onChange={(event) => setFormField('mainPostingCode', event.target.value)} required>
                    <option value="" disabled>
                      Select main posting
                    </option>
                    {sortedPostingCodeOptions.map((postingCode) => (
                      <option key={postingCode.code} value={postingCode.code}>
                        {postingOptionLabel(postingCode)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Fallback posting, optional
                  <select value={formState.exclusionCode} onChange={(event) => setFormField('exclusionCode', event.target.value)}>
                    <option value="">No fallback posting</option>
                    {sortedPostingCodeOptions.map((postingCode) => (
                      <option key={postingCode.code} value={postingCode.code}>
                        {postingOptionLabel(postingCode)}
                      </option>
                    ))}
                  </select>
                </label>
                <p className="admin-config-helper">
                  The RDB parser stores this posting on the next RDB upload. Used when no recognised Posting 1 match is found in an FM main-posting cell.
                </p>
              </div>
            ) : null}

            {activeTab === 'half_month' ? (
              <p className="admin-config-helper">
                The RDB parser splits active month weight 50/50 between these postings on the next RDB upload.
              </p>
            ) : null}
          </div>

          {submitState === 'error' && feedback ? (
            <div className="inline-callout callout-error">{feedback.message}</div>
          ) : null}
        </form>
      </DetailDrawer>
    </>
  )
}

export const AdminMultiPostingPage = () => (
  <Navigate to="/admin/config" state={{ configSection: 'multi-posting-rules' }} replace />
)
