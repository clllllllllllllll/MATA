import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useAppState } from '../context/useAppState'
import {
  clearMemoryCache,
  getMemoryCache,
  makeScopedCacheKey,
  readThroughMemoryCache,
  type CacheScope,
} from '../utils/memoryReadCache'

type ConfigCacheParams = Record<string, string | number | boolean | null | undefined>

interface UseAdminConfigReadCacheOptions<T> {
  section: string
  params?: ConfigCacheParams
  initialData: T
  fetcher: () => Promise<T>
  errorMessage: string
}

interface AdminConfigReadCacheResult<T> {
  data: T
  loading: boolean
  isRefreshing: boolean
  error: string | null
  reload: (options?: { force?: boolean }) => Promise<void>
}

export const useAdminConfigReadCache = <T,>({
  section,
  params,
  initialData,
  fetcher,
  errorMessage,
}: UseAdminConfigReadCacheOptions<T>): AdminConfigReadCacheResult<T> => {
  const { role, demoAdminId, demoAdminProgrammes } = useAppState()
  const cacheScope = useMemo<CacheScope>(() => ({
    role,
    userId: demoAdminId,
    programmeScope: demoAdminProgrammes,
  }), [demoAdminId, demoAdminProgrammes, role])
  const cacheKey = makeScopedCacheKey(cacheScope, 'admin.config', {
    section,
    ...(params ?? {}),
  })
  const initialDataRef = useRef(initialData)
  const currentKeyRef = useRef(cacheKey)
  const hasLoadedRef = useRef(Boolean(getMemoryCache<T>(cacheKey)))
  const mountedRef = useRef(true)
  const [data, setData] = useState<T>(() => getMemoryCache<T>(cacheKey)?.data ?? initialData)
  const [loading, setLoading] = useState(() => !getMemoryCache<T>(cacheKey))
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    initialDataRef.current = initialData
  }, [initialData])

  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  const reload = useCallback(async (options?: { force?: boolean }) => {
    const keyChanged = currentKeyRef.current !== cacheKey
    if (keyChanged) {
      currentKeyRef.current = cacheKey
    }

    const cached = options?.force ? undefined : getMemoryCache<T>(cacheKey)
    if (cached) {
      setData(cached.data)
      hasLoadedRef.current = true
      setLoading(false)
    } else if (keyChanged) {
      setData(initialDataRef.current)
      hasLoadedRef.current = false
    }

    const backgroundRefetch = Boolean(cached) || (!keyChanged && hasLoadedRef.current)
    if (backgroundRefetch) {
      setIsRefreshing(true)
      setLoading(false)
    } else {
      setLoading(true)
    }
    setError(null)

    try {
      if (options?.force) {
        clearMemoryCache((key) => key === cacheKey)
      }
      const { data: nextData } = await readThroughMemoryCache(
        cacheKey,
        fetcher,
        { force: Boolean(cached) || options?.force === true },
      )
      if (!mountedRef.current) {
        return
      }
      setData(nextData)
      hasLoadedRef.current = true
    } catch (loadError) {
      if (!mountedRef.current) {
        return
      }
      if (!backgroundRefetch) {
        setData(initialDataRef.current)
      }
      hasLoadedRef.current = true
      setError(loadError instanceof Error ? loadError.message : errorMessage)
    } finally {
      if (mountedRef.current) {
        setLoading(false)
        setIsRefreshing(false)
      }
    }
  }, [cacheKey, errorMessage, fetcher])

  useEffect(() => {
    mountedRef.current = true
    queueMicrotask(() => {
      if (mountedRef.current) {
        void reload()
      }
    })
  }, [reload])

  return { data, loading, isRefreshing, error, reload }
}
