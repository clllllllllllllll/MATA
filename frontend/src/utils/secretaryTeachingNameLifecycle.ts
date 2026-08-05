export interface TeachingNameLifecycleError {
  message: string
  needsRefresh: boolean
}

interface TeachingNameApiError {
  status?: number
  message?: string
}

export const resolveTeachingNameLifecycleConflict = (
  error: TeachingNameApiError,
): TeachingNameLifecycleError | null => {
  const message = error.message ?? ''
  if (error.status === 409 && /changed; refresh and retry/i.test(message)) {
    return {
      message: 'This Teaching Name was changed by someone else. Refresh the list and retry.',
      needsRefresh: true,
    }
  }
  if (error.status === 409 && /already exists|normalized value/i.test(message)) {
    return {
      message: 'A Teaching Name with this name already exists in the selected programme and reporting period.',
      needsRefresh: false,
    }
  }
  if (error.status === 409 && /in use/i.test(message)) {
    return {
      message: 'This Teaching Name is in use and cannot be deleted. Deactivate it instead.',
      needsRefresh: true,
    }
  }
  return null
}
