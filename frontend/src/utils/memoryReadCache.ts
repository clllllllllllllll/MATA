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

const memoryCache = new Map<string, MemoryCacheEntry<unknown>>()

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
    memoryCache.clear()
    return
  }

  Array.from(memoryCache.keys()).forEach((key) => {
    if (predicate(key)) {
      memoryCache.delete(key)
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

  const data = await fetcher()
  setMemoryCache(key, data)
  return { data, fromCache: false }
}
