/** Analysis starts with Diagnose; keep all other command positions unchanged. */
export function orderToolTabs<T extends { name: string }>(commands: readonly T[]): T[] {
  const ordered = [...commands]
  const diagnose = ordered.findIndex(command => command.name === 'diagnose')
  const cluster = ordered.findIndex(command => command.name === 'cluster')
  if (diagnose >= 0 && cluster >= 0 && cluster < diagnose) {
    [ordered[diagnose], ordered[cluster]] = [ordered[cluster], ordered[diagnose]]
  }
  return ordered
}
