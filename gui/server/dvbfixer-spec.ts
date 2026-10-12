/** Runtime form schema generated from DVBfixer's argparse command surface. */

export type FlagType = 'bool' | 'number' | 'text' | 'select' | 'artifact'

export interface FlagDef {
  flag: string
  dest: string
  label: string
  type: FlagType
  group: string
  default?: string | number | boolean | Array<string | number>
  options?: Array<string | number>
  help?: string
  required?: boolean
  repeatable?: boolean
  multi?: boolean
  falseFlag?: string
  exclusiveGroup?: string
  name?: string
  nargs?: string | number | null
}

export interface FieldGroup {
  name: string
  fields: string[]
}

export interface CommandDef {
  name: string
  label: string
  description: string
  category: string
  inputs: FlagDef[]
  flags: FlagDef[]
  groups: FieldGroup[]
  outputExtension: string
  outputMode: 'file' | 'prefix' | 'directory' | 'stdout'
  backendOutputModes?: Record<string, 'file' | 'prefix' | 'directory' | 'stdout'>
  hasOutput: boolean
  outputKind: 'artifact' | 'report'
  batch: boolean
  successCodes: number[]
  specialized?: boolean
}

export { GENERATED_COMMANDS as COMMANDS } from './generated-dvbfixer-spec'
