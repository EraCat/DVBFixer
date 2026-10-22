import type { components } from '../generated/dvbfixer-api'
import { v1Client } from './v1-client'

type NamingRequest = components['schemas']['NamingConversionRequest']
export type NamingResponse = components['schemas']['NamingConversionResponse']
type Artifact = { id: string; file: string }

/** Adapt GUI fields to the naming contract, never to the managed-job contract. */
export async function runNamingConversion(
  workspaceId: string,
  inputFile: string,
  artifacts: readonly Artifact[],
  values: Record<string, unknown>,
  readOverrides: (file: string) => Promise<unknown>,
): Promise<NamingResponse> {
  const input = artifacts.find(artifact => artifact.file === inputFile)
  if (!input) throw new Error('Select an input artifact from the current workspace')
  const forceField = values['--target-ff']
  if (forceField !== 'amber' && forceField !== 'amber19sb' && forceField !== 'charmm') {
    throw new Error('Target FF is required')
  }
  const profile = values['--profile'] ?? 'gromacs'
  if (profile !== 'gromacs' && profile !== 'standard') throw new Error('Select a supported naming profile')
  const body: NamingRequest = {
    inputArtifactId: input.id, target: { forceField, profile }, dryRun: values['--dry-run'] === true,
  }
  if (values['--infer-protonation'] === true) body.inferProtonation = true
  const overridesFile = values['--variant-overrides']
  if (overridesFile) {
    if (typeof overridesFile !== 'string' || !artifacts.some(artifact => artifact.file === overridesFile)) {
      throw new Error('Select a variant-overrides JSON artifact from the current workspace')
    }
    const overrides = await readOverrides(overridesFile)
    if (!Array.isArray(overrides) || overrides.length > 10_000) {
      throw new Error('Variant overrides must be a JSON array with at most 10,000 entries')
    }
    // The API validates the exact override schema. No naming science in JS.
    body.variantOverrides = overrides as NamingRequest['variantOverrides']
  }
  const { data, error, response } = await v1Client.POST(
    '/api/v1/workspaces/{workspaceId}/naming-conversions', {
      params: { path: { workspaceId } }, body,
    },
  )
  if (error) throw new Error(error.error.message || `Naming conversion: HTTP ${response.status}`)
  if (!data) throw new Error('Naming conversion returned no result')
  return data
}

export function namingOutputMatches(
  result: { workspaceId: string } | null, workspaceId: string | undefined, command: string | undefined,
): boolean {
  return command === 'atom-names' && !!workspaceId && result?.workspaceId === workspaceId
}
