export type PcSessionTypesPendingAction =
  | 'mapping-impact-preview'
  | 'mapping-mutation'
  | 'bulk-impact-preview'
  | 'bulk-mutation'
  | 'lifecycle-mutation'

export type PcSessionTypesOverlay =
  | 'name-drawer'
  | 'single-confirmation'
  | 'bulk-confirmation'

export interface PcSessionTypesInteractionSnapshot {
  pendingAction: PcSessionTypesPendingAction | null
  overlay: PcSessionTypesOverlay | null
}

export interface PcSessionTypesInteractionCoordinator {
  snapshot: () => PcSessionTypesInteractionSnapshot
  tryBegin: (action: PcSessionTypesPendingAction) => boolean
  transitionPending: (
    current: PcSessionTypesPendingAction,
    next: PcSessionTypesPendingAction,
  ) => boolean
  beginWithinOverlay: (
    overlay: PcSessionTypesOverlay,
    action: PcSessionTypesPendingAction,
  ) => boolean
  replacePendingWithOverlay: (
    action: PcSessionTypesPendingAction,
    overlay: PcSessionTypesOverlay,
  ) => boolean
  openOverlay: (overlay: PcSessionTypesOverlay) => boolean
  closeOverlay: (overlay?: PcSessionTypesOverlay) => boolean
  complete: (action: PcSessionTypesPendingAction) => boolean
  reset: () => void
}

export const createPcSessionTypesInteractionCoordinator = (): PcSessionTypesInteractionCoordinator => {
  let pendingAction: PcSessionTypesPendingAction | null = null
  let overlay: PcSessionTypesOverlay | null = null

  const snapshot = (): PcSessionTypesInteractionSnapshot => ({ pendingAction, overlay })

  return {
    snapshot,
    tryBegin: (action) => {
      if (pendingAction !== null || overlay !== null) {
        return false
      }
      pendingAction = action
      return true
    },
    transitionPending: (current, next) => {
      if (pendingAction !== current) {
        return false
      }
      pendingAction = next
      return true
    },
    beginWithinOverlay: (expectedOverlay, action) => {
      if (pendingAction !== null || overlay !== expectedOverlay) {
        return false
      }
      pendingAction = action
      return true
    },
    replacePendingWithOverlay: (action, nextOverlay) => {
      if (pendingAction !== action || overlay !== null) {
        return false
      }
      pendingAction = null
      overlay = nextOverlay
      return true
    },
    openOverlay: (nextOverlay) => {
      if (pendingAction !== null) {
        return false
      }
      overlay = nextOverlay
      return true
    },
    closeOverlay: (expectedOverlay) => {
      if (overlay === null || (expectedOverlay !== undefined && overlay !== expectedOverlay)) {
        return false
      }
      overlay = null
      return true
    },
    complete: (action) => {
      if (pendingAction !== action) {
        return false
      }
      pendingAction = null
      return true
    },
    reset: () => {
      pendingAction = null
      overlay = null
    },
  }
}
