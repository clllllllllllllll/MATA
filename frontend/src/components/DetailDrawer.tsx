import type { ReactNode } from 'react'

interface DetailDrawerProps {
  title: string
  open: boolean
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}

export const DetailDrawer = ({
  title,
  open,
  onClose,
  children,
  footer,
}: DetailDrawerProps) => {
  if (!open) {
    return null
  }

  return (
    <>
      <button type="button" className="scrim drawer-backdrop" onClick={onClose} aria-label="Close drawer" />
      <aside className="drawer" aria-modal="true" role="dialog">
        <header className="drawer-header">
          <h2 className="drawer-title">{title}</h2>
          <button type="button" className="button btn button-ghost btn-ghost" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer ? <footer className="drawer-footer">{footer}</footer> : null}
      </aside>
    </>
  )
}
