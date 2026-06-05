import { useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { breadcrumbMap, navItems, roleOptions } from '../config/navigation'
import { useAppState } from '../context/useAppState'
import type { AppRole } from '../types/app'
import {
  IconCheck,
  IconChevDown,
  IconChevRight,
  IconLogOut,
  IconSettings,
  NamedIcon,
} from './icons'

const roleNameById: Record<AppRole, string> = {
  master_admin: 'Demo Admin',
  programme_pc: 'Demo PC',
  secretary: 'Demo Secretary',
  resident: 'Demo Resident',
  external_resident: 'Demo External',
}

const roleFromPathname = (pathname: string): AppRole | null => {
  if (pathname === '/admin/config' || pathname.startsWith('/admin/config/')) {
    return null
  }
  if (pathname.startsWith('/secretary')) {
    return 'secretary'
  }
  if (pathname.startsWith('/resident')) {
    return 'resident'
  }
  if (pathname.startsWith('/external')) {
    return 'external_resident'
  }
  if (pathname.startsWith('/pc')) {
    return 'programme_pc'
  }
  if (pathname.startsWith('/admin')) {
    return 'master_admin'
  }
  return null
}

export const AppShell = () => {
  const { role, setRole, warnings } = useAppState()
  const location = useLocation()
  const navigate = useNavigate()
  const [isRoleMenuOpen, setRoleMenuOpen] = useState(false)
  const roleMenuRef = useRef<HTMLDivElement | null>(null)
  const forcedRole = roleFromPathname(location.pathname)
  const activeRole = forcedRole ?? role

  const currentRoleOption = roleOptions.find((option) => option.id === activeRole) ?? roleOptions[0]
  const breadcrumbs =
    activeRole === 'programme_pc' && location.pathname.startsWith('/admin/config')
      ? location.pathname === '/admin/config/multi'
        ? ['Programme PC', 'Configuration', 'Multi-Posting Rules']
        : ['Programme PC', 'Configuration']
      : breadcrumbMap[location.pathname] ?? [currentRoleOption.label]
  const unresolvedWarningsCount = warnings.filter((warning) => warning.status === 'unresolved').length
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
    if (path === '/secretary/events') {
      return currentPath === '/secretary' || currentPath === '/secretary/events'
    }
    if (path === '/resident/submissions') {
      return currentPath === '/resident' || currentPath === '/resident/submissions'
    }
    return currentPath === path || currentPath.startsWith(`${path}/`)
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

  useEffect(() => {
    if (forcedRole && role !== forcedRole) {
      setRole(forcedRole)
    }
  }, [forcedRole, role, setRole])

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
            <div className="avatar">{roleNameById[activeRole].slice(0, 2).toUpperCase()}</div>
            <div className="sidebar-user-details">
              <strong>{roleNameById[activeRole]}</strong>
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
                  const isCurrent = option.id === activeRole
                  return (
                    <button
                      key={option.id}
                      type="button"
                      className={`role-switcher-option ${isCurrent ? 'is-current' : ''}`}
                      onClick={() => {
                        setRole(option.id)
                        setRoleMenuOpen(false)
                        navigate(option.defaultPath)
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
              <p className="role-switcher-note">Demo aid only - not in production.</p>
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
          <button type="button">
            <span className="sidebar-footer-icon" aria-hidden="true">
              <IconSettings size={16} />
            </span>
            <span>Settings</span>
          </button>
          <button type="button">
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






