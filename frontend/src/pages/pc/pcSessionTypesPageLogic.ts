import type {
  ProgrammePcTeachingNameMapping,
  TeachingNameMappingTarget,
} from '../../api/pcTeachingNameMappings'

export const targetOptionLabel = (target: TeachingNameMappingTarget): string => {
  const qualifiers = [
    `${target.monthlyTarget} per month`,
    target.isTracked ? 'tracked' : 'not tracked',
    target.isReallocatable ? 'reallocatable' : 'not reallocatable',
    target.tag ? `tag: ${target.tag}` : null,
  ].filter((value): value is string => Boolean(value))
  return `${target.sessionTypeName} — ${qualifiers.join(' · ')}`
}

export const targetOptionsForMapping = (
  mapping: ProgrammePcTeachingNameMapping,
): TeachingNameMappingTarget[] => {
  const byId = new Map<string, TeachingNameMappingTarget>()
  mapping.availableTargetOptions.forEach((target) => {
    if (target.id) {
      byId.set(target.id, target)
    }
  })
  if (mapping.target?.id && !byId.has(mapping.target.id)) {
    byId.set(mapping.target.id, mapping.target)
  }
  return [...byId.values()]
}
