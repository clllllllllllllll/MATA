import { useEffect, useId, type ReactNode } from 'react'
import { IconX } from './icons'

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
  const titleId = useId()

  useEffect(() => {
    if (!open) {
      return
    }

    const previousOverflow = document.body.style.overflow
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
      }
    }

    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', onEscape)

    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onEscape)
    }
  }, [onClose, open])

  if (!open) {
    return null
  }

  return (
    <>
      <button type="button" className="scrim drawer-backdrop" onClick={onClose} aria-label="Close drawer" />
      <aside className="drawer" aria-modal="true" aria-labelledby={titleId} role="dialog">
        <header className="drawer-header">
          <h2 className="drawer-title" id={titleId}>{title}</h2>
          <button
            type="button"
            className="button btn button-ghost btn-ghost drawer-close-button"
            onClick={onClose}
            aria-label="Close drawer"
          >
            <IconX size={18} />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer ? <footer className="drawer-footer">{footer}</footer> : null}
      </aside>
    </>
  )
}
