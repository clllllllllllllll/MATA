import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react'
import {
  createStaffAccount,
  listStaffAccounts,
  resetStaffAccountPassword,
  updateStaffAccount,
  type StaffAccount,
  type StaffAccountType,
} from '../../api/staffAccounts'
import { listPostingCodes, type PostingCodeOption } from '../../api/postingCodes'
import { listProgrammes, type Programme } from '../../api/programmes'
import { DetailDrawer } from '../../components/DetailDrawer'
import { IconPlus, IconRefresh } from '../../components/icons'
import { PageHero } from '../../components/PageHero'
import { StatusBadge } from '../../components/StatusBadge'
import { useAppState } from '../../context/useAppState'
import { useAuth } from '../../context/useAuth'
import { formatUserFacingApiError } from '../../utils/userFacingErrors'

type DrawerMode = 'create' | 'edit'

interface StaffAccountFormState {
  accountDisplayName: string
  email: string
  password: string
  accountType: StaffAccountType
  isActive: boolean
  programmeScope: string[]
  postingCode: string
}

const emptyForm: StaffAccountFormState = {
  accountDisplayName: '',
  email: '',
  password: '',
  accountType: 'programme_pc',
  isActive: true,
  programmeScope: [],
  postingCode: '',
}

const accountTypeLabels: Record<StaffAccountType, string> = {
  master_admin: 'Master Admin',
  programme_pc: 'PC',
  secretary: 'Secretary',
}

const scopeText = (account: StaffAccount) => {
  if (account.accountType === 'master_admin') {
    return 'All programmes'
  }
  if (account.accountType === 'programme_pc') {
    return account.programmeScope.length > 0 ? account.programmeScope.join(', ') : 'No programme scope'
  }
  return account.postingCode ?? 'No posting'
}

const formatProgrammeLabel = (programme: Programme) =>
  programme.name ? `${programme.code} - ${programme.name}` : programme.code

const formatPostingLabel = (posting: PostingCodeOption) =>
  posting.displayName ? `${posting.code} - ${posting.displayName}` : posting.code

const accountToForm = (account: StaffAccount): StaffAccountFormState => ({
  accountDisplayName: account.accountDisplayName,
  email: account.email,
  password: '',
  accountType: account.accountType,
  isActive: account.isActive,
  programmeScope: account.programmeScope,
  postingCode: account.postingCode ?? '',
})

export const AdminStaffAccountsPage = () => {
  const { demoAdminId, demoAdminProgrammes } = useAppState()
  const { identity } = useAuth()
  const [accounts, setAccounts] = useState<StaffAccount[]>([])
  const [programmes, setProgrammes] = useState<Programme[]>([])
  const [postingCodes, setPostingCodes] = useState<PostingCodeOption[]>([])
  const [loading, setLoading] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [drawerMode, setDrawerMode] = useState<DrawerMode>('create')
  const [selectedAccount, setSelectedAccount] = useState<StaffAccount | null>(null)
  const [formState, setFormState] = useState<StaffAccountFormState>(emptyForm)
  const [submitMessage, setSubmitMessage] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [resetAccount, setResetAccount] = useState<StaffAccount | null>(null)
  const [resetPassword, setResetPassword] = useState('')
  const [resetMessage, setResetMessage] = useState<string | null>(null)
  const [resetSubmitting, setResetSubmitting] = useState(false)

  const requestContext = useMemo(() => ({
    adminId: identity?.subjectId ?? demoAdminId,
    adminProgrammes: identity?.role === 'programme_pc' ? identity.programmeScope : demoAdminProgrammes,
  }), [demoAdminId, demoAdminProgrammes, identity])

  const refresh = useCallback(async () => {
    setLoading(true)
    setErrorMessage(null)
    try {
      const [accountRows, programmeRows, postingRows] = await Promise.all([
        listStaffAccounts(requestContext),
        listProgrammes({
          adminId: requestContext.adminId,
          adminProgrammes: requestContext.adminProgrammes,
          adminLevel: 'master',
        }),
        listPostingCodes({
          adminId: requestContext.adminId,
          adminProgrammes: requestContext.adminProgrammes,
          adminLevel: 'master',
        }),
      ])
      setAccounts(accountRows)
      setProgrammes(programmeRows)
      setPostingCodes(postingRows)
    } catch (error) {
      setErrorMessage(formatUserFacingApiError(error, {
        fallbackMessage: 'Unable to load staff accounts.',
      }))
    } finally {
      setLoading(false)
    }
  }, [requestContext])

  useEffect(() => {
    void Promise.resolve().then(refresh)
  }, [refresh])

  const openCreateDrawer = () => {
    setDrawerMode('create')
    setSelectedAccount(null)
    setFormState(emptyForm)
    setSubmitMessage(null)
    setDrawerOpen(true)
  }

  const openEditDrawer = (account: StaffAccount) => {
    setDrawerMode('edit')
    setSelectedAccount(account)
    setFormState(accountToForm(account))
    setSubmitMessage(null)
    setDrawerOpen(true)
  }

  const setFormField = <K extends keyof StaffAccountFormState>(
    field: K,
    value: StaffAccountFormState[K],
  ) => {
    setFormState((current) => ({ ...current, [field]: value }))
  }

  const validateForm = () => {
    if (!formState.accountDisplayName.trim()) {
      return 'Account display name is required.'
    }
    if (drawerMode === 'create' && !formState.email.trim()) {
      return 'Email/login is required.'
    }
    if (drawerMode === 'create' && formState.password.trim().length < 8) {
      return 'Password must be at least 8 characters.'
    }
    if (formState.accountType === 'programme_pc' && formState.programmeScope.length === 0) {
      return 'PC requires at least one programme.'
    }
    if (formState.accountType === 'secretary' && !formState.postingCode.trim()) {
      return 'Secretary requires a posting code.'
    }
    return null
  }

  const payloadFromForm = () => ({
    accountDisplayName: formState.accountDisplayName.trim(),
    accountType: formState.accountType,
    isActive: formState.isActive,
    programmeScope: formState.accountType === 'programme_pc' ? formState.programmeScope : undefined,
    postingCode: formState.accountType === 'secretary' ? formState.postingCode : undefined,
  })

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const validationMessage = validateForm()
    if (validationMessage) {
      setSubmitMessage(validationMessage)
      return
    }

    setSubmitting(true)
    setSubmitMessage(null)
    try {
      if (drawerMode === 'create') {
        await createStaffAccount({
          ...requestContext,
          payload: {
            ...payloadFromForm(),
            email: formState.email.trim(),
            password: formState.password.trim(),
          },
        })
      } else if (selectedAccount) {
        await updateStaffAccount({
          ...requestContext,
          id: selectedAccount.id,
          payload: payloadFromForm(),
        })
      }
      setDrawerOpen(false)
      await refresh()
    } catch (error) {
      setSubmitMessage(formatUserFacingApiError(error, {
        fallbackMessage: 'Unable to save staff account.',
      }))
    } finally {
      setSubmitting(false)
    }
  }

  const toggleActive = async (account: StaffAccount) => {
    setErrorMessage(null)
    try {
      await updateStaffAccount({
        ...requestContext,
        id: account.id,
        payload: {
          accountDisplayName: account.accountDisplayName,
          accountType: account.accountType,
          isActive: !account.isActive,
          programmeScope: account.programmeScope,
          postingCode: account.postingCode,
        },
      })
      await refresh()
    } catch (error) {
      setErrorMessage(formatUserFacingApiError(error, {
        fallbackMessage: 'Unable to update staff account.',
      }))
    }
  }

  const handleResetPassword = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!resetAccount) {
      return
    }
    if (resetPassword.trim().length < 8) {
      setResetMessage('Password must be at least 8 characters.')
      return
    }

    setResetSubmitting(true)
    setResetMessage(null)
    try {
      await resetStaffAccountPassword({
        ...requestContext,
        id: resetAccount.id,
        password: resetPassword.trim(),
      })
      setResetAccount(null)
      setResetPassword('')
      await refresh()
    } catch (error) {
      setResetMessage(formatUserFacingApiError(error, {
        fallbackMessage: 'Unable to reset password.',
      }))
    } finally {
      setResetSubmitting(false)
    }
  }

  return (
    <div className="page admin-staff-accounts-page">
      <PageHero
        title="Staff Accounts"
        subtitle="Master Admin account management"
        actions={(
          <div className="hero-action-row">
            <button
              type="button"
              className="button button-secondary"
              onClick={() => void refresh()}
              disabled={loading}
            >
              <IconRefresh size={14} />
              Refresh
            </button>
            <button type="button" className="button button-primary" onClick={openCreateDrawer}>
              <IconPlus size={14} />
              New staff account
            </button>
          </div>
        )}
      />

      {errorMessage ? <div className="notice notice-error">{errorMessage}</div> : null}

      <section className="card">
        <div className="table-wrap">
          <div className="table-scroll">
            <table className="admin-staff-accounts-table">
              <thead>
                <tr>
                  <th>Account display name</th>
                  <th>Email/login</th>
                  <th>Account type</th>
                  <th>Scope</th>
                  <th>Current staff name</th>
                  <th>Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr>
                    <td colSpan={7}>Loading staff accounts...</td>
                  </tr>
                ) : accounts.length === 0 ? (
                  <tr>
                    <td colSpan={7}>No staff accounts found.</td>
                  </tr>
                ) : (
                  accounts.map((account) => (
                    <tr key={account.id}>
                      <td>{account.accountDisplayName}</td>
                      <td>{account.email}</td>
                      <td>{accountTypeLabels[account.accountType]}</td>
                      <td>{scopeText(account)}</td>
                      <td>{account.currentStaffActorName ?? 'Not set'}</td>
                      <td>
                        <StatusBadge
                          label={account.isActive ? 'Active' : 'Inactive'}
                          tone={account.isActive ? 'success' : 'neutral'}
                        />
                      </td>
                      <td>
                        <div className="staff-account-actions">
                          <div className="staff-account-actions-primary">
                            <button
                              type="button"
                              className="button button-ghost staff-account-action-button"
                              onClick={() => openEditDrawer(account)}
                            >
                              Edit
                            </button>
                            <button
                              type="button"
                              className={
                                account.isActive
                                  ? 'button button-ghost danger staff-account-action-button'
                                  : 'button button-ghost staff-account-action-button'
                              }
                              onClick={() => void toggleActive(account)}
                            >
                              {account.isActive ? 'Deactivate' : 'Activate'}
                            </button>
                          </div>
                          <button
                            type="button"
                            className="button button-ghost staff-account-action-button staff-account-reset-button"
                            onClick={() => {
                              setResetAccount(account)
                              setResetPassword('')
                              setResetMessage(null)
                            }}
                          >
                            Reset password
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <DetailDrawer
        title={drawerMode === 'create' ? 'Create staff account' : 'Edit staff account'}
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        footer={(
          <>
            <button
              type="button"
              className="button button-secondary"
              onClick={() => setDrawerOpen(false)}
              disabled={submitting}
            >
              Cancel
            </button>
            <button type="submit" form="staff-account-form" className="button button-primary" disabled={submitting}>
              {submitting ? 'Saving' : drawerMode === 'create' ? 'Create account' : 'Save changes'}
            </button>
          </>
        )}
      >
        <form id="staff-account-form" className="secretary-form-grid" onSubmit={(event) => void handleSubmit(event)}>
          <label>
            <span>Account display name</span>
            <input
              value={formState.accountDisplayName}
              onChange={(event) => setFormField('accountDisplayName', event.target.value)}
            />
          </label>
          <label>
            <span>Email/login</span>
            <input
              type="email"
              value={formState.email}
              onChange={(event) => setFormField('email', event.target.value)}
              disabled={drawerMode === 'edit'}
            />
          </label>
          {drawerMode === 'create' ? (
            <label>
              <span>Password</span>
              <input
                type="password"
                value={formState.password}
                onChange={(event) => setFormField('password', event.target.value)}
                autoComplete="new-password"
              />
            </label>
          ) : null}
          <label>
            <span>Account type</span>
            <select
              value={formState.accountType}
              onChange={(event) => setFormField('accountType', event.target.value as StaffAccountType)}
            >
              <option value="master_admin">Master Admin</option>
              <option value="programme_pc">PC</option>
              <option value="secretary">Secretary</option>
            </select>
          </label>
          <div className="secretary-toggle-block staff-account-toggle-block">
            <span className="secretary-toggle-label">Active account</span>
            <div className="secretary-yes-no">
              <button
                type="button"
                className={formState.isActive ? 'is-active' : ''}
                onClick={() => setFormField('isActive', true)}
              >
                Yes
              </button>
              <button
                type="button"
                className={!formState.isActive ? 'is-active' : ''}
                onClick={() => setFormField('isActive', false)}
              >
                No
              </button>
            </div>
          </div>
          {formState.accountType === 'programme_pc' ? (
            <label>
              <span>Programme scope</span>
              <select
                value={formState.programmeScope[0] ?? ''}
                onChange={(event) =>
                  setFormField('programmeScope', event.target.value ? [event.target.value] : [])
                }
              >
                <option value="">Select programme</option>
                {programmes.map((programme) => (
                  <option value={programme.code} key={programme.code}>
                    {formatProgrammeLabel(programme)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {formState.accountType === 'secretary' ? (
            <label>
              <span>Posting code</span>
              <select
                value={formState.postingCode}
                onChange={(event) => setFormField('postingCode', event.target.value)}
              >
                <option value="">Select posting</option>
                {postingCodes.map((posting) => (
                  <option value={posting.code} key={posting.code}>
                    {formatPostingLabel(posting)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          {submitMessage ? <div className="notice notice-error">{submitMessage}</div> : null}
        </form>
      </DetailDrawer>

      {resetAccount ? (
        <>
          <button
            type="button"
            className="scrim staff-settings-backdrop"
            aria-label="Cancel password reset"
            onClick={() => setResetAccount(null)}
          />
          <section className="staff-settings-modal" aria-modal="true" aria-labelledby="reset-password-title" role="dialog">
            <form onSubmit={(event) => void handleResetPassword(event)}>
              <header className="staff-settings-header">
                <h2 id="reset-password-title">Reset password</h2>
              </header>
              <div className="staff-settings-body">
                <div className="staff-settings-row">
                  <span>Account</span>
                  <strong>{resetAccount.accountDisplayName}</strong>
                </div>
                <label className="auth-field">
                  <span>New password</span>
                  <input
                    type="password"
                    value={resetPassword}
                    onChange={(event) => setResetPassword(event.target.value)}
                    autoComplete="new-password"
                    disabled={resetSubmitting}
                  />
                </label>
                <p className="muted">Resetting the password clears the saved staff name for handover.</p>
                {resetMessage ? <div className="auth-error">{resetMessage}</div> : null}
              </div>
              <footer className="staff-settings-footer">
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setResetAccount(null)}
                  disabled={resetSubmitting}
                >
                  Cancel
                </button>
                <button type="submit" className="button button-primary" disabled={resetSubmitting}>
                  {resetSubmitting ? 'Resetting' : 'Reset password'}
                </button>
              </footer>
            </form>
          </section>
        </>
      ) : null}
    </div>
  )
}
