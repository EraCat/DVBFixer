import { COMMANDS } from './dvbfixer-spec'

/** Build a validated argv fragment from values and the generated CLI contract. */
export function buildArgs(commandName: string, values: Record<string, any>): string[] {
  const def = COMMANDS.find(command => command.name === commandName)
  if (!def) throw new Error(`Unknown DVBFixer command: ${commandName}`)
  const args: string[] = []
  for (const flag of def.flags) {
    const value = values[flag.flag]
    if (value === undefined || value === '' || value === null) continue
    if (flag.type === 'bool') {
      if (value === true) args.push(flag.flag)
      else if (value === false && flag.falseFlag) args.push(flag.falseFlag)
    } else if (flag.repeatable && Array.isArray(value)) {
      for (const item of value) if (String(item).trim()) args.push(flag.flag, String(item))
    } else if (flag.multi && Array.isArray(value)) {
      const items = value.map(String).filter(Boolean)
      if (items.length) args.push(flag.flag, ...items)
    } else if (flag.repeatable && typeof value === 'string') {
      for (const item of value.split(',').map(item => item.trim()).filter(Boolean)) {
        args.push(flag.flag, ...(flag.multi ? item.split(/\s+/).filter(Boolean) : [item]))
      }
    } else if (flag.type === 'number') {
      args.push(flag.flag, String(value))
    } else if (flag.multi && typeof value === 'string') {
      const items = value.split(/\s+/).map(item => item.trim()).filter(Boolean)
      if (items.length) args.push(flag.flag, ...items)
    } else {
      args.push(flag.flag, String(value))
    }
  }
  return args
}
