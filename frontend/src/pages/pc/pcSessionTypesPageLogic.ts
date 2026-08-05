import type {
  ProgrammePcTeachingNameMapping,
  TeachingNameMappingTarget,
} from '../../api/pcTeachingNameMappings'

export const MAX_BULK_MAPPING_ITEMS = 100

export interface PreparedBulkMappingItem {
  mappingId: string
  expectedRevision: number
  teachingTargetId: string | null
}

export type PreparedBulkMappingChanges =
  | { kind: 'ready'; items: PreparedBulkMappingItem[] }
  | { kind: 'invalid'; message: string }

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

export const prepareBulkMappingChanges = (
  mappings: ProgrammePcTeachingNameMapping[],
  selectedMappingIds: ReadonlySet<string>,
  draftTargetIds: Readonly<Record<string, string>>,
): PreparedBulkMappingChanges => {
  if (selectedMappingIds.size === 0) {
    return { kind: 'invalid', message: 'Select at least one mapping to apply prepared changes.' }
  }
  if (selectedMappingIds.size > MAX_BULK_MAPPING_ITEMS) {
    return {
      kind: 'invalid',
      message: `Bulk mapping is limited to ${MAX_BULK_MAPPING_ITEMS} rows.`,
    }
  }

  const mappingsById = new Map(mappings.map((mapping) => [mapping.id, mapping]))
  const items: PreparedBulkMappingItem[] = []
  for (const mappingId of selectedMappingIds) {
    const mapping = mappingsById.get(mappingId)
    if (!mapping) {
      return { kind: 'invalid', message: 'The selected mapping is no longer in this queue. Refresh and retry.' }
    }
    const currentTargetId = mapping.teachingTargetId ?? ''
    const draftTargetId = draftTargetIds[mapping.id] ?? currentTargetId
    if (draftTargetId === currentTargetId) {
      return {
        kind: 'invalid',
        message: 'Choose a different exact target or clear an existing mapping for every selected row.',
      }
    }
    if (draftTargetId && !targetOptionsForMapping(mapping).some((target) => target.id === draftTargetId)) {
      return { kind: 'invalid', message: 'One selected target is no longer available for its exact mapping scope.' }
    }
    items.push({
      mappingId: mapping.id,
      expectedRevision: mapping.revision,
      teachingTargetId: draftTargetId || null,
    })
  }
  return { kind: 'ready', items }
}
