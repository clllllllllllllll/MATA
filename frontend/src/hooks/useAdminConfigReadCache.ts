import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useAppState } from '../context/useAppState'
import {
  clearMemoryCache,
  getMemoryCache,
  isMemoryCacheInvalidatedError,
  makeScopedCacheKey,
  readThroughMemoryCache,
} from '../utils/memoryReadCache'
import {
  captureProtectedAsyncRequestFence,
  isProtectedAsyncRequestFenceCurrent,
} from '../utils/protectedAsyncFence'

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
  const { authCacheScope } = useAppState()
  const cacheKey = makeScopedCacheKey(authCacheScope, 'admin.config', {
    section,
    ...(params ?? {}),
  })
  const initialDataRef = useRef(initialData)
  const currentKeyRef = useRef(cacheKey)
  const loadedKeyRef = useRef(cacheKey)
  const requestIdRef = useRef(0)
  const hasLoadedRef = useRef(Boolean(getMemoryCache<T>(cacheKey)))
  const mountedRef = useRef(true)
  const [data, setData] = useState<T>(() => getMemoryCache<T>(cacheKey)?.data ?? initialData)
  const [loading, setLoading] = useState(() => !getMemoryCache<T>(cacheKey))
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useLayoutEffect(() => {
    currentKeyRef.current = cacheKey
    requestIdRef.current += 1
  }, [cacheKey])

  useEffect(() => {
    initialDataRef.current = initialData
  }, [initialData])

  useEffect(() => {
    return () => {
      mountedRef.current = false
    }
  }, [])

  const reload = useCallback(async (options?: { force?: boolean }) => {
    const requestId = requestIdRef.current + 1
    requestIdRef.current = requestId
    const requestFence = captureProtectedAsyncRequestFence(cacheKey, requestId)
    const isCurrentRequest = () => mountedRef.current
      && isProtectedAsyncRequestFenceCurrent(
        requestFence,
        currentKeyRef.current,
        requestIdRef.current,
      )
    const keyChanged = loadedKeyRef.current !== cacheKey
    loadedKeyRef.current = cacheKey

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
      if (!isCurrentRequest()) {
        return
      }
      setData(nextData)
      hasLoadedRef.current = true
    } catch (loadError) {
      if (isMemoryCacheInvalidatedError(loadError) || !isCurrentRequest()) {
        return
      }
      if (!backgroundRefetch) {
        setData(initialDataRef.current)
      }
      hasLoadedRef.current = true
      setError(loadError instanceof Error ? loadError.message : errorMessage)
    } finally {
      if (isCurrentRequest()) {
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
