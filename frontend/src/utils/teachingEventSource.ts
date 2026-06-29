export const teachingEventCreatedByLabel = (createdByRole?: string | null): string => {
  switch (createdByRole) {
    case 'secretary':
      return 'Secretary'
    case 'programme_pc':
      return 'PC'
    default:
      return 'Legacy'
  }
}

export const teachingEventCreatedByDisplay = (createdByRole?: string | null): string =>
  `Created by: ${teachingEventCreatedByLabel(createdByRole)}`
