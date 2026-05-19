import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { breadcrumbMap, navItems, roleOptions } from '../config/navigation'
import { useAppState } from '../context/useAppState'
import type { AppRole } from '../types/app'
import {
  IconCheck,
  IconChevDown,
  IconChevRight,
  NamedIcon,
} from './icons'

const roleNameById: Record<AppRole, string> = {
  master_admin: 'Demo Admin',
  programme_pc: 'Demo PC',
  secretary: 'Demo Secretary',
  resident: 'Demo Resident',
  external_resident: 'Demo External',
}

export const AppShell = () => {
  const { role, setRole, warnings } = useAppState()
  const location = useLocation()
  const [isRoleMenuOpen, setRoleMenuOpen] = useState(false)
  const roleMenuRef = useRef<HTMLDivElement | null>(null)

  const currentRoleOption = roleOptions.find((option) => option.id === role) ?? roleOptions[0]
  const breadcrumbs = breadcrumbMap[location.pathname] ?? [currentRoleOption.label]
  const unresolvedWarningsCount = warnings.filter((warning) => warning.status === 'unresolved').length
  const visibleNavItems = navItems.filter((item) => item.roles.includes(role))

  const isNavActive = (path: string) => {
    const currentPath = location.pathname
    if (path === '/admin') {
      return currentPath === '/admin'
    }
    if (path === '/admin/upload') {
      return currentPath === '/admin/upload'
    }
    if (path === '/admin/upload/warnings') {
      return currentPath === '/admin/upload/warnings'
    }
    if (path === '/admin/config/multi') {
      return currentPath === '/admin/config/multi' || currentPath.startsWith('/admin/config/')
    }
    if (path === '/admin/upload-logs') {
      return currentPath === '/admin/upload-logs'
    }
    if (path === '/admin/parsed-data') {
      return currentPath === '/admin/parsed-data'
    }
    if (path === '/admin/secretary-events') {
      return currentPath === '/admin/secretary-events'
    }
    if (path === '/admin/submissions') {
      return currentPath === '/admin/submissions'
    }
    return currentPath === path
  }

  useEffect(() => {
    const onPointerDown = (event: MouseEvent) => {
      if (!roleMenuRef.current?.contains(event.target as Node)) {
        setRoleMenuOpen(false)
      }
    }
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setRoleMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onEscape)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onEscape)
    }
  }, [])

  return (
    <div className="app app-root">
      <aside className="sidebar">
        <div className="sidebar-user-wrap" ref={roleMenuRef}>
        <button
          type="button"
          className="sidebar-user"
          onClick={() => setRoleMenuOpen((prev) => !prev)}
          aria-haspopup="menu"
          aria-expanded={isRoleMenuOpen}
        >
          <div className="avatar">{roleNameById[role].slice(0, 2).toUpperCase()}</div>
          <div className="sidebar-user-details">
            <strong>{roleNameById[role]}</strong>
            <p>{currentRoleOption.label}</p>
          </div>
          <span className={`sidebar-user-chevron ${isRoleMenuOpen ? 'is-open' : ''}`} aria-hidden="true">
            <IconChevDown size={16} />
          </span>
        </button>

        {isRoleMenuOpen ? (
          <div className="role-switcher-popover" role="menu" aria-label="Role Switcher">
            <p className="role-switcher-title">SWITCH ROLE (DEMO AID)</p>
            <div className="role-switcher-list">
              {roleOptions.map((option) => {
                const isCurrent = option.id === role
                return (
                  <button
                    key={option.id}
                    type="button"
                    className={`role-switcher-option ${isCurrent ? 'is-current' : ''}`}
                    onClick={() => {
                      setRole(option.id)
                      setRoleMenuOpen(false)
                    }}
                    role="menuitemradio"
                    aria-checked={isCurrent}
                  >
                    <span className="role-switcher-option-main">{option.label}</span>
                    <span className="role-switcher-option-scope">{option.scopeLabel}</span>
                    {isCurrent ? (
                      <span className="role-switcher-check" aria-hidden="true">
                        <IconCheck size={14} />
                      </span>
                    ) : null}
                  </button>
                )
              })}
            </div>
            <p className="role-switcher-note">Demo aid only — not in production.</p>
          </div>
        ) : null}
        </div>

        <nav className="sidebar-nav">
          {visibleNavItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className={isNavActive(item.path) ? 'sidebar-link is-active' : 'sidebar-link'}
            >
              <span className="nav-icon" aria-hidden="true">
                <NamedIcon name={item.icon} size={18} />
              </span>
              <span className="nav-label">{item.label}</span>
              {item.path === '/admin/upload/warnings' && unresolvedWarningsCount > 0 ? (
                <span className="nav-count">{unresolvedWarningsCount}</span>
              ) : null}
            </NavLink>
          ))}
        </nav>

        <div className="sidebar-scope">
          <span>Scope</span>
          <strong>{currentRoleOption.scopeLabel}</strong>
        </div>

        <div className="sidebar-footer-links">
          <button type="button">Settings</button>
          <button type="button">Log out</button>
        </div>
      </aside>

      <div className="workspace app-main">
        <header className="appbar app-bar">
          <div className="appbar-inner">
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
          <Outlet />
        </main>
      </div>
    </div>
  )
}
