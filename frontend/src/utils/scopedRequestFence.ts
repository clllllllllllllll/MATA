export interface ScopedRequestToken {
  scopeKey: string | null
  sequence: number
}

export interface ScopedRequestFence {
  begin: (scopeKey: string | null) => ScopedRequestToken
  invalidate: () => void
  isCurrent: (token: ScopedRequestToken, currentScopeKey: string | null) => boolean
}

export const createScopedRequestFence = (): ScopedRequestFence => {
  let latestSequence = 0

  return {
    begin: (scopeKey) => ({
      scopeKey,
      sequence: ++latestSequence,
    }),
    invalidate: () => {
      latestSequence += 1
    },
    isCurrent: (token, currentScopeKey) => (
      token.sequence === latestSequence && token.scopeKey === currentScopeKey
    ),
  }
}
