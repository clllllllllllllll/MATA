export type TeachingNameOptionsState = 'unavailable' | 'loading' | 'error' | 'empty' | 'ready'

export interface TeachingNameOptionsStateInput {
  hasContext: boolean
  isLoading: boolean
  isLoaded: boolean
  error: string | null
  optionCount: number
}

export const resolveTeachingNameOptionsState = ({
  hasContext,
  isLoading,
  isLoaded,
  error,
  optionCount,
}: TeachingNameOptionsStateInput): TeachingNameOptionsState => {
  if (!hasContext) {
    return 'unavailable'
  }
  if (isLoading || !isLoaded) {
    return 'loading'
  }
  if (error) {
    return 'error'
  }
  return optionCount > 0 ? 'ready' : 'empty'
}

export const canAddTeachingFromOptions = (state: TeachingNameOptionsState): boolean =>
  state === 'ready'
