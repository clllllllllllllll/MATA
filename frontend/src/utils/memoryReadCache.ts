export type MemoryCacheEntry<T> = {
  data: T
  fetchedAt: number
}

export type CacheScope = {
  role?: string
  userId?: string
  programmeScope?: string[]
  postingCode?: string
  residentId?: string
}

export class MemoryCacheInvalidatedError extends Error {
  constructor() {
    super('The protected cache was invalidated while the request was in flight.')
    this.name = 'MemoryCacheInvalidatedError'
  }
}

export const isMemoryCacheInvalidatedError = (
  error: unknown,
): error is MemoryCacheInvalidatedError => error instanceof MemoryCacheInvalidatedError

const memoryCache = new Map<string, MemoryCacheEntry<unknown>>()
let memoryCacheGeneration = 0
const memoryCacheKeyGenerations = new Map<string, number>()
const inFlightMemoryCacheReads = new Map<string, number>()

const memoryCacheKeyGeneration = (key: string): number =>
  memoryCacheKeyGenerations.get(key) ?? 0

const beginMemoryCacheRead = (key: string): void => {
  inFlightMemoryCacheReads.set(
    key,
    (inFlightMemoryCacheReads.get(key) ?? 0) + 1,
  )
}

const finishMemoryCacheRead = (key: string): void => {
  const remaining = (inFlightMemoryCacheReads.get(key) ?? 1) - 1
  if (remaining > 0) {
    inFlightMemoryCacheReads.set(key, remaining)
  } else {
    inFlightMemoryCacheReads.delete(key)
  }
}

const stableValue = (value: unknown): unknown => {
  if (Array.isArray(value)) {
    return value.map(stableValue)
  }
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => item !== undefined)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, stableValue(item)]),
    )
  }
  return value
}

const stableStringify = (value: unknown) => JSON.stringify(stableValue(value))

const normaliseScope = (scope: CacheScope): CacheScope => ({
  ...scope,
  programmeScope: scope.programmeScope ? [...scope.programmeScope].sort() : undefined,
})

export const makeScopedCacheKey = (
  scope: CacheScope,
  resource: string,
  params: unknown,
): string => stableStringify({
  scope: normaliseScope(scope),
  resource,
  params,
})

export const getMemoryCache = <T,>(key: string): MemoryCacheEntry<T> | undefined => {
  return memoryCache.get(key) as MemoryCacheEntry<T> | undefined
}

export const setMemoryCache = <T,>(key: string, data: T): void => {
  memoryCache.set(key, {
    data,
    fetchedAt: Date.now(),
  })
}

export const clearMemoryCache = (predicate?: (key: string) => boolean): void => {
  if (!predicate) {
    memoryCacheGeneration += 1
    memoryCache.clear()
    memoryCacheKeyGenerations.clear()
    return
  }

  const candidateKeys = new Set([
    ...memoryCache.keys(),
    ...inFlightMemoryCacheReads.keys(),
  ])
  candidateKeys.forEach((key) => {
    if (predicate(key)) {
      memoryCache.delete(key)
      memoryCacheKeyGenerations.set(
        key,
        memoryCacheKeyGeneration(key) + 1,
      )
    }
  })
}

export const clearMemoryCacheResource = (resource: string): void => {
  clearMemoryCache((key) => key.includes(`"resource":"${resource}"`))
}

export const readThroughMemoryCache = async <T,>(
  key: string,
  fetcher: () => Promise<T>,
  options?: { force?: boolean },
): Promise<{ data: T; fromCache: boolean }> => {
  if (!options?.force) {
    const cached = getMemoryCache<T>(key)
    if (cached) {
      return { data: cached.data, fromCache: true }
    }
  }

  const requestGeneration = memoryCacheGeneration
  const requestKeyGeneration = memoryCacheKeyGeneration(key)
  const requestWasInvalidated = () =>
    requestGeneration !== memoryCacheGeneration
    || requestKeyGeneration !== memoryCacheKeyGeneration(key)
  beginMemoryCacheRead(key)
  try {
    const data = await fetcher()
    if (requestWasInvalidated()) {
      throw new MemoryCacheInvalidatedError()
    }
    setMemoryCache(key, data)
    return { data, fromCache: false }
  } catch (error) {
    if (
      !(error instanceof MemoryCacheInvalidatedError)
      && requestWasInvalidated()
    ) {
      throw new MemoryCacheInvalidatedError()
    }
    throw error
  } finally {
    finishMemoryCacheRead(key)
  }
}
