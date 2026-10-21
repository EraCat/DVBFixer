import { afterEach, describe, expect, it, vi } from 'vitest'
import { namingOutputMatches, runNamingConversion, type NamingResponse } from './naming-conversion'

const artifacts = [{ id: 'input-id', file: 'inputs/a.pdb' }, { id: 'overrides-id', file: 'inputs/variants.json' }]
const result: NamingResponse = {
  operationId: 'operation', status: 'succeeded', sourceArtifactId: 'input-id',
  outputArtifact: { id: 'output-id', file: 'runs/named.pdb', name: 'named.pdb', kind: 'structure' },
  output: { bytes: 100, sha256: 'a'.repeat(64) },
  result: { model: 1, summary: { changedAtoms: 1, changedResidues: 0, variantChanges: 0, atomNameChanges: 1 }, changes: [], diagnostics: [] },
}

afterEach(() => { vi.unstubAllGlobals() })

describe('GUI atom-names transport', () => {
  it.each(['gromacs', 'standard'])('submits %s to naming-conversions, not managed jobs', async profile => {
    const calls: Request[] = []
    vi.stubGlobal('fetch', vi.fn(async (input, init) => {
      calls.push(new Request(input, init))
      return Response.json(result, { status: 201 })
    }))
    const read = vi.fn()
    expect(await runNamingConversion('workspace-a', artifacts[0].file, artifacts,
      { '--target-ff': 'amber19sb', '--profile': profile }, read)).toEqual(result)
    expect(calls).toHaveLength(1)
    expect(new URL(calls[0].url).pathname).toBe('/api/v1/workspaces/workspace-a/naming-conversions')
    expect(calls[0].method).toBe('POST')
    expect(await calls[0].json()).toEqual({
      inputArtifactId: 'input-id', target: { forceField: 'amber19sb', profile }, dryRun: false,
    })
    expect(read).not.toHaveBeenCalled()
  })

  it('sends dry-run and inline overrides without publishing a fake output', async () => {
    const overrides = [{ chainId: 'd', residueNumber: '82', insertionCode: 'A', variant: 'HIE' }]
    const read = vi.fn(async () => overrides)
    const fetch = vi.fn(async (input, init) => {
      const body = await new Request(input, init).json()
      expect(body.dryRun).toBe(true)
      expect(body.variantOverrides).toEqual(overrides)
      return Response.json({ ...result, outputArtifact: null })
    })
    vi.stubGlobal('fetch', fetch)
    const response = await runNamingConversion('workspace-a', artifacts[0].file, artifacts, {
      '--target-ff': 'charmm', '--dry-run': true, '--variant-overrides': artifacts[1].file,
    }, read)
    expect(response.outputArtifact).toBeNull()
    expect(read).toHaveBeenCalledWith(artifacts[1].file)
  })

  it.each([
    ['outside.pdb', { '--target-ff': 'amber' }],
    [artifacts[0].file, {}],
    [artifacts[0].file, { '--target-ff': 'amber', '--variant-overrides': 'outside.json' }],
    [artifacts[0].file, { '--target-ff': 'amber', '--profile': 'unknown' }],
  ] as const)('rejects invalid fields without submitting a job', async (file, values) => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(runNamingConversion('workspace-a', file, artifacts, values, vi.fn())).rejects.toThrow()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('reports server validation errors without a fallback to /jobs', async () => {
    const fetch = vi.fn(async () => Response.json({ error: { code: 'NAMING_COLLISION', message: 'Atom names collide' } }, { status: 422 }))
    vi.stubGlobal('fetch', fetch)
    await expect(runNamingConversion('workspace-a', artifacts[0].file, artifacts,
      { '--target-ff': 'amber' }, vi.fn())).rejects.toThrow('Atom names collide')
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('rejects invalid overrides before submission', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    await expect(runNamingConversion('workspace-a', artifacts[0].file, artifacts, {
      '--target-ff': 'amber', '--variant-overrides': artifacts[1].file,
    }, async () => ({ invalid: true }))).rejects.toThrow('JSON array')
    expect(fetch).not.toHaveBeenCalled()
  })

  it('never shows naming output in another tool or workspace', () => {
    const output = { workspaceId: 'a' }
    expect(namingOutputMatches(output, 'a', 'atom-names')).toBe(true)
    expect(namingOutputMatches(output, 'b', 'atom-names')).toBe(false)
    expect(namingOutputMatches(output, 'a', 'diagnose')).toBe(false)
    expect(namingOutputMatches(null, 'a', 'atom-names')).toBe(false)
  })
})
