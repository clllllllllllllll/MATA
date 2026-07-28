const MEBIBYTE_BYTES = 1024 * 1024

export const MAX_UPLOAD_FILE_SIZE_MIB = 3
export const MAX_UPLOAD_REQUEST_SIZE_MIB = 4
export const MAX_REQUEST_BODY_SIZE_MIB = 4

export const MAX_UPLOAD_FILE_SIZE_BYTES =
  MAX_UPLOAD_FILE_SIZE_MIB * MEBIBYTE_BYTES

export const UPLOAD_FILE_SIZE_HELP_TEXT =
  `Maximum file size: ${MAX_UPLOAD_FILE_SIZE_MIB} MiB.`

export const UPLOAD_FILE_SIZE_ERROR_MESSAGE =
  `File is too large. Choose a file no larger than ${MAX_UPLOAD_FILE_SIZE_MIB} MiB.`

export const UPLOAD_REQUEST_SIZE_ERROR_MESSAGE =
  `Upload request is too large. The complete request is limited to ${MAX_UPLOAD_REQUEST_SIZE_MIB} MiB, including a file no larger than ${MAX_UPLOAD_FILE_SIZE_MIB} MiB.`

interface UploadFileCandidate {
  name: string
  size: number
}

export const validateUploadFile = (
  candidate: UploadFileCandidate,
  accept: string,
): string | null => {
  const acceptedExtensions = accept
    .split(',')
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean)
  const fileName = candidate.name.toLowerCase()

  if (!acceptedExtensions.some((extension) => fileName.endsWith(extension))) {
    return `Invalid file type. Allowed: ${acceptedExtensions.join(', ')}`
  }
  if (candidate.size > MAX_UPLOAD_FILE_SIZE_BYTES) {
    return UPLOAD_FILE_SIZE_ERROR_MESSAGE
  }
  return null
}
