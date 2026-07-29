interface BrowserStorage {
  removeItem(key: string): void
}

export const LEGACY_MATA_AUTH_SESSION_KEY = 'mata.auth.session.v1'

export const removeKnownLegacyCredentials = (
  storage: BrowserStorage,
): void => {
  storage.removeItem(LEGACY_MATA_AUTH_SESSION_KEY)
}

export const clearKnownLegacyBrowserCredentials = (): void => {
  for (const getStorage of [
    () => window.localStorage,
    () => window.sessionStorage,
  ]) {
    try {
      removeKnownLegacyCredentials(getStorage())
    } catch {
      // The current cookie flow is independent of this residue. A blocked
      // browser persistence API must not prevent the application from starting.
    }
  }
}
