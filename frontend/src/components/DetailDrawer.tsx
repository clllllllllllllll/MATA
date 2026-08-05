import { useEffect, useId, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { IconX } from './icons'
import { focusTrapTargetIndex } from '../utils/drawerFocus'

const focusableSelector = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(', ')

const getFocusableDrawerElements = (drawer: HTMLElement | null) => {
  if (!drawer) {
    return []
  }
  return Array.from(drawer.querySelectorAll<HTMLElement>(focusableSelector)).filter(
    (element) => element.getAttribute('aria-hidden') !== 'true',
  )
}

interface DetailDrawerProps {
  title: string
  open: boolean
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  closeDisabled?: boolean
  busy?: boolean
}

export const DetailDrawer = ({
  title,
  open,
  onClose,
  children,
  footer,
  closeDisabled = false,
  busy = false,
}: DetailDrawerProps) => {
  const titleId = useId()
  const drawerRef = useRef<HTMLElement | null>(null)
  const closeButtonRef = useRef<HTMLButtonElement | null>(null)
  const backdropRef = useRef<HTMLButtonElement | null>(null)

  useEffect(() => {
    if (!open) {
      return
    }

    const previousActiveElement = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null
    const frame = window.requestAnimationFrame(() => {
      const initialField = drawerRef.current?.querySelector<HTMLElement>(
        'input:not([disabled]), select:not([disabled]), textarea:not([disabled])',
      )
      ;(initialField ?? closeButtonRef.current)?.focus()
    })

    return () => {
      window.cancelAnimationFrame(frame)
      if (previousActiveElement?.isConnected) {
        window.requestAnimationFrame(() => previousActiveElement.focus())
      }
    }
  }, [open])

  useEffect(() => {
    if (!open) {
      return
    }

    const previousOverflow = document.body.style.overflow
    const backgroundElements = Array.from(document.body.children)
      .filter((element) => element !== drawerRef.current && element !== backdropRef.current)
      .map((element) => ({
        element,
        hadInert: element.hasAttribute('inert'),
        previousAriaHidden: element.getAttribute('aria-hidden'),
      }))
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !closeDisabled) {
        onClose()
        return
      }
      if (event.key !== 'Tab') {
        return
      }

      const focusableElements = getFocusableDrawerElements(drawerRef.current)
      if (focusableElements.length === 0) {
        event.preventDefault()
        drawerRef.current?.focus()
        return
      }

      const activeElementIndex = focusableElements.indexOf(document.activeElement as HTMLElement)
      const nextIndex = focusTrapTargetIndex(
        activeElementIndex,
        focusableElements.length,
        event.shiftKey,
      )
      if (nextIndex !== null) {
        event.preventDefault()
        focusableElements[nextIndex]?.focus()
      }
    }

    document.body.style.overflow = 'hidden'
    backgroundElements.forEach(({ element }) => {
      element.setAttribute('inert', '')
      element.setAttribute('aria-hidden', 'true')
    })
    document.addEventListener('keydown', onKeyDown)

    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', onKeyDown)
      backgroundElements.forEach(({ element, hadInert, previousAriaHidden }) => {
        if (!hadInert) {
          element.removeAttribute('inert')
        }
        if (previousAriaHidden === null) {
          element.removeAttribute('aria-hidden')
        } else {
          element.setAttribute('aria-hidden', previousAriaHidden)
        }
      })
    }
  }, [closeDisabled, onClose, open])

  if (!open) {
    return null
  }

  return createPortal(
    <>
      <button
        ref={backdropRef}
        type="button"
        className="scrim drawer-backdrop"
        onClick={onClose}
        aria-label={closeDisabled ? 'Close drawer unavailable while action is pending' : 'Close drawer'}
        disabled={closeDisabled}
      />
      <aside
        ref={drawerRef}
        className="drawer"
        aria-busy={busy || undefined}
        aria-modal="true"
        aria-labelledby={titleId}
        role="dialog"
        tabIndex={-1}
      >
        <header className="drawer-header">
          <h2 className="drawer-title" id={titleId}>{title}</h2>
          <button
            ref={closeButtonRef}
            type="button"
            className="button btn button-ghost btn-ghost drawer-close-button"
            onClick={onClose}
            aria-label={closeDisabled ? 'Close drawer unavailable while action is pending' : 'Close drawer'}
            disabled={closeDisabled}
          >
            <IconX size={18} />
          </button>
        </header>
        <div className="drawer-body">{children}</div>
        {footer ? <footer className="drawer-footer">{footer}</footer> : null}
      </aside>
    </>,
    document.body,
  )
}
