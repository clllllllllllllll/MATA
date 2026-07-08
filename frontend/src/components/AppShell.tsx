import { useEffect, useRef, useState } from 'react'
import type { FormEvent, PropsWithChildren } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { breadcrumbMap, navItems, roleOptions } from '../config/navigation'
import { useAuth } from '../context/useAuth'
import { useAppState } from '../context/useAppState'
import type { AppRole } from '../types/app'
import {
  effectiveProgrammePcScope,
  formatProgrammePcSidebarTitle,
} from '../utils/programmePcLabels'
import { formatUserFacingApiError } from '../utils/userFacingErrors'
import {
  IconChevRight,
  IconLogOut,
  IconMenu,
  IconSettings,
  IconX,
  NamedIcon,
} from './icons'

const roleNameById: Record<AppRole, string> = {
  master_admin: 'Demo Admin',
  programme_pc: 'Demo PC',
  secretary: 'Demo Secretary',
  resident: 'Demo Resident',
  external_resident: 'Demo Non-NHG',
}

export const AppShell = ({ children }: PropsWithChildren) => {
  const { role } = useAppState()
  const { identity, logout, updateStaffActorName } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const [mobileNavOpenPath, setMobileNavOpenPath] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [settingsName, setSettingsName] = useState('')
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const roleMenuRef = useRef<HTMLDivElement | null>(null)
  const activeRole = identity?.role ?? role
  const isMobileNavOpen = mobileNavOpenPath === location.pathname
  const isStaffIdentity =
    identity?.role === 'master_admin' ||
    identity?.role === 'programme_pc' ||
    identity?.role === 'secretary'

  const currentRoleOption = roleOptions.find((option) => option.id === activeRole) ?? roleOptions[0]
  const currentDisplayName =
    identity?.role === 'programme_pc' && activeRole === 'programme_pc'
      ? formatProgrammePcSidebarTitle(identity.programmeScope)
      : identity?.role === activeRole && identity.name
        ? identity.name
        : roleNameById[activeRole]
  const isResidentIdentity = identity?.role === 'resident' || identity?.role === 'external_resident'
  const sidebarSubtext = isResidentIdentity ? identity.mcr : currentRoleOption.label
  const currentPostingScope = isResidentIdentity
    ? identity.currentPostingLabel ?? identity.currentPostingCode ?? 'No current posting'
    : null
  const currentScopeLabel = (() => {
    if (identity?.role === 'master_admin' && activeRole === 'master_admin') {
      return 'All Programmes'
    }
    if (identity?.role === 'programme_pc' && activeRole === 'programme_pc') {
      return effectiveProgrammePcScope(identity.programmeScope) ?? 'No programme scope'
    }
    if (identity?.role === 'secretary' && activeRole === 'secretary') {
      return identity.postingCode
    }
    if (identity?.role === 'resident' && activeRole === 'resident') {
      return currentPostingScope ?? 'No current posting'
    }
    if (identity?.role === 'external_resident' && activeRole === 'external_resident') {
      return currentPostingScope ?? 'No current posting'
    }
    return currentRoleOption.scopeLabel
  })()
  const breadcrumbs = breadcrumbMap[location.pathname] ?? [currentRoleOption.label]
  const visibleNavItems = navItems.filter((item) => item.roles.includes(activeRole))

  const isNavActive = (path: string) => {
    const currentPath = location.pathname
    if (path === '/admin') {
      return currentPath === '/admin'
    }
    if (path === '/admin/upload') {
      return currentPath === '/admin/upload'
    }
    if (path === '/admin/config') {
      return currentPath === '/admin/config' || currentPath.startsWith('/admin/config/')
    }
    if (path === '/pc/config') {
      return currentPath === '/pc/config'
    }
    if (path === '/secretary/events') {
      return currentPath === '/secretary' || currentPath === '/secretary/events'
    }
    if (path === '/resident/submissions') {
      return currentPath === '/resident' || currentPath === '/resident/submissions'
    }
    return currentPath === path || currentPath.startsWith(`${path}/`)
  }

  useEffect(() => {
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setMobileNavOpenPath(null)
      }
    }
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('keydown', onEscape)
    }
  }, [])

  useEffect(() => {
    if (!isMobileNavOpen) {
      return
    }

    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [isMobileNavOpen])

  const closeMobileNav = () => setMobileNavOpenPath(null)

  const openSettings = () => {
    if (!isStaffIdentity) {
      return
    }
    setSettingsName(identity?.currentStaffActorName ?? '')
    setSettingsError(null)
    setSettingsOpen(true)
  }

  const handleSettingsSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const trimmedName = settingsName.trim()
    if (!trimmedName) {
      setSettingsError('Full name is required.')
      return
    }

    setSettingsSaving(true)
    setSettingsError(null)
    try {
      await updateStaffActorName(trimmedName)
      setSettingsOpen(false)
    } catch (error) {
      setSettingsError(formatUserFacingApiError(error, {
        fallbackMessage: 'Unable to save staff name.',
      }))
    } finally {
      setSettingsSaving(false)
    }
  }

  return (
    <div className={`app app-root ${isMobileNavOpen ? 'mobile-nav-is-open' : ''}`}>
      {isMobileNavOpen ? (
        <button
          type="button"
          className="mobile-nav-backdrop"
          aria-label="Close navigation"
          onClick={closeMobileNav}
        />
      ) : null}
      <aside className={`sidebar ${isMobileNavOpen ? 'is-mobile-open' : ''}`} aria-label="Primary navigation">
        <button
          type="button"
          className="mobile-nav-close"
          aria-label="Close navigation"
          onClick={closeMobileNav}
        >
          <IconX size={18} />
        </button>

        <div className="sidebar-user-wrap" ref={roleMenuRef}>
          <div className="sidebar-user" aria-label="Current user">
            <div className="avatar">{currentDisplayName.slice(0, 2).toUpperCase()}</div>
            <div className="sidebar-user-details">
              <strong>{currentDisplayName}</strong>
              <p>{sidebarSubtext}</p>
            </div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {visibleNavItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={closeMobileNav}
              className={isNavActive(item.path) ? 'sidebar-link is-active' : 'sidebar-link'}
            >
              <span className="nav-icon" aria-hidden="true">
                <NamedIcon name={item.icon} size={18} />
              </span>
              <span className="nav-label">{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-scope">
          <span>Scope</span>
          <strong>{currentScopeLabel}</strong>
        </div>

        <div className="sidebar-footer-links">
          <button
            type="button"
            aria-label="Settings"
            title="Settings"
            onClick={openSettings}
            disabled={!isStaffIdentity}
          >
            <span className="sidebar-footer-icon" aria-hidden="true">
              <IconSettings size={16} />
            </span>
            <span>Settings</span>
          </button>
          <button
            type="button"
            aria-label="Log out"
            title="Log out"
            onClick={() => {
              void (async () => {
                await logout()
                navigate('/login', { replace: true })
              })()
            }}
          >
            <span className="sidebar-footer-icon" aria-hidden="true">
              <IconLogOut size={16} />
            </span>
            <span>Log out</span>
          </button>
        </div>
      </aside>

      <div className="workspace app-main">
        <header className="appbar app-bar">
          <div className="appbar-inner">
            <button
              type="button"
              className="mobile-nav-toggle"
              aria-label="Open navigation"
              aria-expanded={isMobileNavOpen}
              onClick={() => setMobileNavOpenPath(location.pathname)}
            >
              <IconMenu size={19} />
            </button>
            <div className="crumbs breadcrumbs">
              {breadcrumbs.map((crumb, index) => (
                <span key={`${crumb}-${index}`}>
                  {index > 0 ? (
                    <span className="sep" aria-hidden="true">
                      <IconChevRight size={12} />
                    </span>
                  ) : null}
                  <span className={index === breadcrumbs.length - 1 ? 'crumb-current is-current' : ''}>
                    {crumb}
                  </span>
                </span>
              ))}
            </div>
          </div>
        </header>

        <main className="content">
          {children ?? <Outlet />}
        </main>
      </div>
      {settingsOpen && isStaffIdentity && identity ? (
        <>
          <button
            type="button"
            className="scrim staff-settings-backdrop"
            aria-label="Close settings"
            onClick={() => setSettingsOpen(false)}
          />
          <section
            className="staff-settings-modal"
            aria-modal="true"
            aria-labelledby="staff-settings-title"
            role="dialog"
          >
            <form onSubmit={(event) => void handleSettingsSubmit(event)}>
              <header className="staff-settings-header">
                <h2 id="staff-settings-title">Staff account settings</h2>
                <button
                  type="button"
                  className="button button-ghost"
                  onClick={() => setSettingsOpen(false)}
                  disabled={settingsSaving}
                >
                  <IconX size={18} />
                </button>
              </header>
              <div className="staff-settings-body">
                <div className="staff-settings-row">
                  <span>Account</span>
                  <strong>{identity.name ?? currentDisplayName}</strong>
                </div>
                <div className="staff-settings-row">
                  <span>Current staff name</span>
                  <strong>{identity.currentStaffActorName ?? 'Not set'}</strong>
                </div>
                <label className="auth-field">
                  <span>Full name</span>
                  <input
                    value={settingsName}
                    onChange={(event) => setSettingsName(event.target.value)}
                    autoComplete="name"
                    disabled={settingsSaving}
                  />
                </label>
                {settingsError ? <div className="auth-error">{settingsError}</div> : null}
              </div>
              <footer className="staff-settings-footer">
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setSettingsOpen(false)}
                  disabled={settingsSaving}
                >
                  Cancel
                </button>
                <button type="submit" className="button button-primary" disabled={settingsSaving}>
                  {settingsSaving ? 'Saving' : 'Save'}
                </button>
              </footer>
            </form>
          </section>
        </>
      ) : null}
    </div>
  )
}




