export const SECRETARY_TEACHING_EVENT_EXPORT_ERROR =
  'Unable to export teaching events. Please try again.'

export interface CsvDownloadEnvironment {
  createObjectUrl: (blob: Blob) => string
  revokeObjectUrl: (url: string) => void
  createLink: () => HTMLAnchorElement
  appendLink: (link: HTMLAnchorElement) => void
  removeLink: (link: HTMLAnchorElement) => void
  defer: (callback: () => void) => void
}

const browserCsvDownloadEnvironment: CsvDownloadEnvironment = {
  createObjectUrl: (blob) => URL.createObjectURL(blob),
  revokeObjectUrl: (url) => URL.revokeObjectURL(url),
  createLink: () => document.createElement('a'),
  appendLink: (link) => document.body.appendChild(link),
  removeLink: (link) => link.remove(),
  defer: (callback) => {
    window.setTimeout(callback, 0)
  },
}

export const downloadSecretaryTeachingScheduleCsv = (
  csv: string,
  environment: CsvDownloadEnvironment = browserCsvDownloadEnvironment,
) => {
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = environment.createObjectUrl(blob)
  let link: HTMLAnchorElement | null = null

  try {
    link = environment.createLink()
    link.href = url
    link.download = 'secretary-teaching-schedule.csv'
    environment.appendLink(link)
    link.click()
  } finally {
    if (link) {
      environment.removeLink(link)
    }
    environment.defer(() => environment.revokeObjectUrl(url))
  }
}
