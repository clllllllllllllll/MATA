export const effectiveProgrammePcScope = (programmeScope: readonly string[] | undefined): string | null => {
  const scope = programmeScope
    ?.map((programmeCode) => programmeCode.trim())
    .find((programmeCode) => programmeCode.length > 0)

  return scope ?? null
}

export const formatProgrammePcSidebarTitle = (programmeScope: readonly string[] | undefined): string => {
  const scope = effectiveProgrammePcScope(programmeScope)
  return scope ? `${scope} PC` : 'PC'
}

export const formatProgrammePcConfigSubtitle = (programmeScope: readonly string[] | undefined): string => {
  const scope = effectiveProgrammePcScope(programmeScope)
  return `PC - ${scope ?? 'No programme scope'}`
}
