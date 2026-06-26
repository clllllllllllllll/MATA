export interface ProgrammeOptionInput {
  code: string
  name?: string | null
}

export interface ProgrammeOption {
  code: string
  label: string
}

export const formatProgrammeOptionLabel = (programme: ProgrammeOptionInput): string => {
  const code = programme.code.trim()
  const name = programme.name?.trim() ?? ''
  return name ? `${code} - ${name}` : code
}
