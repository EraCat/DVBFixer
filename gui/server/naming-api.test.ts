import { afterEach, describe, expect, it, vi } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { Readable } from 'node:stream'
import { Value } from '@sinclair/typebox/value'
import { executeNamingConversion, registerNamingApi } from './naming-api'
import {
  NAMING_OPENAPI_DOCUMENT,
  NAMING_REQUEST_EXAMPLE,
  NamingConversionRequestSchema,
  type NamingConversionRequest,
} from './naming-api-schema'
import { loadWorkspace, saveWorkspace, workspaceRoot, type WorkspaceManifest } from './workspace-api'
import {
  DEFAULT_MAX_UPLOAD_BYTES, DEFAULT_WORKSPACE_QUOTA_BYTES, initializeStorageQuota,
  workspaceLogicalBytes,
} from './storage-quota'

const temporaryDirectories: string[] = []

function temp(): string {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'dvbfixer-naming-api-test-'))
  temporaryDirectories.push(directory)
  return directory
}

function workspace(dataRoot: string, id = 'workspace-a'): WorkspaceManifest {
  const root = workspaceRoot(dataRoot, id)
  fs.mkdirSync(path.join(root, 'files'), { recursive: true })
  fs.writeFileSync(path.join(root, 'files', 'input.pdb'), 'ATOM      1  CA  ALA A   1      10.000  10.000  10.000  1.00 20.00           C  \nEND\n')
  return saveWorkspace(dataRoot, {
    version: 1, revision: 0, id, name: id,
    createdAt: new Date(0).toISOString(), updatedAt: new Date(0).toISOString(),
    primaryFile: null, secondaryFile: null,
    artifacts: [{ id: 'source', file: 'files/input.pdb', name: 'input.pdb', kind: 'structure' }],
    toolState: {},
  })
}

const request: NamingConversionRequest = {
  inputArtifactId: 'source',
  target: { forceField: 'amber', profile: 'gromacs' },
  variantOverrides: [],
  outputName: 'named.pdb',
  dryRun: false,
}

function successfulRunner(options: {
  dryRun?: boolean
  beforeWrite?: () => void
  outputSha256?: string
  outputBytes?: Buffer
  outputSymlink?: string
  stdout?: string
  stderr?: string
} = {}) {
  return async (_command: string, args: string[]) => {
    options.beforeWrite?.()
    const output = args[args.indexOf('-o') + 1]
    const reportFile = args[args.indexOf('--report-json') + 1]
    const targetForceField = args[args.indexOf('--target-ff') + 1]
    const outputBytes = options.outputBytes || Buffer.from('ATOM      1  CA  ALA A   1      10.000  10.000  10.000  1.00 20.00           C  \nEND\n')
    const digest = options.outputSha256 || await import('node:crypto').then(({ default: crypto }) =>
      crypto.createHash('sha256').update(outputBytes).digest('hex'))
    if (options.outputSymlink) fs.symlinkSync(options.outputSymlink, output)
    else if (!options.dryRun) fs.writeFileSync(output, outputBytes)
    fs.writeFileSync(reportFile, JSON.stringify({
      schemaVersion: 1,
      operation: 'pdb-force-field-naming',
      status: 'success',
      tool: { name: 'dvbfixer', version: '0.8.5' },
      request: {
        targetForceField, profile: args[args.indexOf('--profile') + 1], dryRun: Boolean(options.dryRun), variantOverrides: [],
      },
      output: { path: output, written: !options.dryRun, bytes: outputBytes.length, sha256: digest },
      result: {
        model: 1,
        summary: { changedAtoms: 0, changedResidues: 0, variantChanges: 0, atomNameChanges: 0 },
        changes: [], diagnostics: [],
      },
      error: null,
    }))
    return { code: 0, stdout: options.stdout || '', stderr: options.stderr || '' }
  }
}

async function apiRequest(
  dataRoot: string,
  method: string,
  url: string,
  body = '',
  contentType = 'application/json',
  runner?: Parameters<typeof executeNamingConversion>[3],
  serviceVersion = 'test-service',
) {
  let middleware: ((req: any, res: any, next: () => void) => Promise<void>) | undefined
  const server = { middlewares: { use: (_route: string, handler: typeof middleware) => { middleware = handler } } }
  registerNamingApi(server as any, dataRoot, runner, undefined, undefined, serviceVersion)
  const incoming = Readable.from([body]) as Readable & {
    method: string; url: string; headers: Record<string, string>
  }
  incoming.method = method
  incoming.url = url
  incoming.headers = { 'content-type': contentType }
  let responseBody = ''
  const headers: Record<string, string> = {}
  const response = {
    statusCode: 0,
    setHeader: (name: string, value: unknown) => { headers[name.toLowerCase()] = String(value) },
    end: (value?: unknown) => { responseBody = value === undefined ? '' : String(value) },
  }
  await middleware!(incoming as any, response as any, () => {})
  return {
    status: response.statusCode,
    headers,
    body: responseBody ? JSON.parse(responseBody) : null,
  }
}

afterEach(() => {
  vi.unstubAllEnvs()
  initializeStorageQuota({
    maxUploadBytes: DEFAULT_MAX_UPLOAD_BYTES,
    workspaceQuotaBytes: DEFAULT_WORKSPACE_QUOTA_BYTES,
  })
  temporaryDirectories.splice(0).forEach(directory =>
    fs.rmSync(directory, { recursive: true, force: true }))
})

describe('naming conversion application boundary', () => {
  it('bounds retained failures and prunes expired diagnostics on a later successful request', async () => {
    vi.stubEnv('DVBFIXER_NAMING_FAILED_MAX_RUNS', '2')
    vi.stubEnv('DVBFIXER_NAMING_FAILED_MAX_AGE_HOURS', '1')
    const dataRoot = temp()
    workspace(dataRoot)
    const root = workspaceRoot(dataRoot, 'workspace-a')
    const failedRoot = path.join(root, 'runs', '_failed')
    for (let index = 0; index < 3; index++) {
      await expect(executeNamingConversion(dataRoot, 'workspace-a', request, async () => ({
        code: -1, stdout: '', stderr: `failure ${index}`, started: true, failure: 'timeout' as const,
      }))).rejects.toMatchObject({ code: 'NAMING_TIMEOUT' })
      const retained = fs.readdirSync(failedRoot)
      expect(retained).toHaveLength(Math.min(index + 1, 2))
      // Make older retained runs unambiguously older than the next failure.
      for (const name of retained) {
        const stamp = new Date(Date.now() - (3 - index) * 1_000)
        fs.utimesSync(path.join(failedRoot, name), stamp, stamp)
      }
    }
    const retained = fs.readdirSync(failedRoot)
    const logs = retained.map(name => fs.readFileSync(path.join(failedRoot, name, 'stderr.log'), 'utf8'))
    expect(logs).toContain('failure 2')
    expect(loadWorkspace(dataRoot, 'workspace-a').artifacts).toHaveLength(1)
    for (const name of retained) fs.utimesSync(path.join(failedRoot, name), new Date(0), new Date(0))
    const result = await executeNamingConversion(dataRoot, 'workspace-a', request, successfulRunner())
    expect(fs.readdirSync(failedRoot)).toEqual([])
    expect(result.statusCode).toBe(201)
    expect(fs.existsSync(path.join(root, result.response.outputArtifact!.file))).toBe(true)
    expect(loadWorkspace(dataRoot, 'workspace-a').artifacts).toHaveLength(2)
  })

  it.each([
    ['DVBFIXER_NAMING_FAILED_MAX_RUNS', '0'],
    ['DVBFIXER_NAMING_FAILED_MAX_RUNS', '1.5'],
    ['DVBFIXER_NAMING_FAILED_MAX_AGE_HOURS', '-1'],
    ['DVBFIXER_NAMING_FAILED_MAX_AGE_HOURS', '9007199254740991'],
  ])('rejects invalid retention setting %s=%s before execution', async (setting, value) => {
    vi.stubEnv(setting, value)
    const dataRoot = temp()
    workspace(dataRoot)
    const runner = vi.fn(successfulRunner())
    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, runner)).rejects.toThrow(setting)
    expect(runner).not.toHaveBeenCalled()
  })

  it('registers exactly one output with complete provenance', async () => {
    const dataRoot = temp()
    workspace(dataRoot)

    const result = await executeNamingConversion(
      dataRoot, 'workspace-a', request, successfulRunner(), undefined, undefined, '9.9.9',
    )

    expect(result.statusCode).toBe(201)
    expect(result.response.outputArtifact?.name).toBe('named.pdb')
    const saved = loadWorkspace(dataRoot, 'workspace-a')
    expect(saved.artifacts).toHaveLength(2)
    const output = saved.artifacts[1]
    expect(output.command).toBe('atom-names')
    expect(output.namingProvenance).toMatchObject({
      operation: 'pdb-force-field-naming', sourceArtifactId: 'source',
      targetForceField: 'amber', profile: 'gromacs', dvbfixerVersion: '0.8.5',
      serviceVersion: '9.9.9',
    })
    expect(output.namingProvenance?.reportSha256).toMatch(/^[a-f0-9]{64}$/)
    expect(output.namingProvenance?.sourceSha256).toMatch(/^[a-f0-9]{64}$/)
    expect(output.namingProvenance?.outputSha256).toBe(result.response.output.sha256)
    expect(fs.readdirSync(path.join(workspaceRoot(dataRoot, 'workspace-a'), output.folder!)))
      .toEqual(['named.pdb'])
    if (process.platform !== 'win32') {
      expect(fs.statSync(path.join(workspaceRoot(dataRoot, 'workspace-a'), output.file)).mode & 0o777)
        .toBe(0o600)
    }
  })

  it('executes and preserves provenance for the Amber19SB naming dialect', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const runner = vi.fn(successfulRunner())
    const amber19Request: NamingConversionRequest = {
      ...request,
      target: { forceField: 'amber19sb', profile: 'gromacs' },
      outputName: 'amber19sb.pdb',
    }

    const result = await executeNamingConversion(
      dataRoot, 'workspace-a', amber19Request, runner,
    )

    expect(runner.mock.calls[0][1]).toContain('amber19sb')
    expect(result.statusCode).toBe(201)
    const output = loadWorkspace(dataRoot, 'workspace-a').artifacts[1]
    expect(output.namingProvenance?.targetForceField).toBe('amber19sb')
  })

  it.each(['amber', 'amber19sb', 'charmm'] as const)('publishes and reloads native %s naming provenance', async forceField => {
    const dataRoot = temp()
    workspace(dataRoot)
    const runner = vi.fn(successfulRunner())
    const nativeRequest: NamingConversionRequest = {
      ...request, target: { forceField, profile: 'standard' }, outputName: undefined,
    }
    const result = await executeNamingConversion(dataRoot, 'workspace-a', nativeRequest, runner)
    const args = runner.mock.calls[0][1]
    expect(args[args.indexOf('--profile') + 1]).toBe('standard')
    expect(result.statusCode).toBe(201)
    expect(result.response.outputArtifact?.name).toMatch(new RegExp(`_${forceField}_standard\\.pdb$`))
    expect(loadWorkspace(dataRoot, 'workspace-a').artifacts[1].namingProvenance)
      .toMatchObject({ targetForceField: forceField, profile: 'standard' })
  })

  it('returns a dry-run report without changing the manifest or retaining output', async () => {
    const dataRoot = temp()
    const before = workspace(dataRoot)
    const dryRequest = { ...request, dryRun: true }

    const result = await executeNamingConversion(
      dataRoot, 'workspace-a', dryRequest, successfulRunner({ dryRun: true }),
    )

    expect(result.statusCode).toBe(200)
    expect(result.response.outputArtifact).toBeNull()
    const saved = loadWorkspace(dataRoot, 'workspace-a')
    expect(saved.revision).toBe(before.revision)
    expect(saved.artifacts).toHaveLength(1)
    expect(fs.readdirSync(path.join(workspaceRoot(dataRoot, 'workspace-a'), 'runs'))).toEqual([])
  })

  it('preserves a concurrent manifest update made while the command runs', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const runner = successfulRunner({
      beforeWrite: () => {
        const latest = loadWorkspace(dataRoot, 'workspace-a')
        latest.toolState.concurrent = 'preserved'
        latest.artifacts.push({ id: 'concurrent', file: 'files/input.pdb', name: 'other', kind: 'structure' })
        saveWorkspace(dataRoot, latest)
      },
    })

    await executeNamingConversion(dataRoot, 'workspace-a', request, runner)

    const saved = loadWorkspace(dataRoot, 'workspace-a')
    expect(saved.toolState.concurrent).toBe('preserved')
    expect(saved.artifacts.map(artifact => artifact.id)).toContain('concurrent')
    expect(saved.artifacts.filter(artifact => artifact.command === 'atom-names')).toHaveLength(1)
  })

  it('does not register an output when its digest disagrees with the report', async () => {
    const dataRoot = temp()
    const before = workspace(dataRoot)

    await expect(executeNamingConversion(
      dataRoot, 'workspace-a', request, successfulRunner({ outputSha256: '0'.repeat(64) }),
    )).rejects.toMatchObject({ code: 'OUTPUT_DIGEST_MISMATCH' })

    const saved = loadWorkspace(dataRoot, 'workspace-a')
    expect(saved.revision).toBe(before.revision)
    expect(saved.artifacts).toHaveLength(1)
    expect(fs.readdirSync(path.join(workspaceRoot(dataRoot, 'workspace-a'), 'runs', '_failed'))).toHaveLength(1)
  })

  it('deletes operation data instead of retaining it when workspace quota is exhausted', async () => {
    const dataRoot = temp()
    const before = workspace(dataRoot)
    const root = workspaceRoot(dataRoot, 'workspace-a')
    const usedBefore = workspaceLogicalBytes(root)
    initializeStorageQuota({
      maxUploadBytes: DEFAULT_MAX_UPLOAD_BYTES,
      workspaceQuotaBytes: usedBefore + 256,
    })

    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, successfulRunner()))
      .rejects.toThrow(/workspace quota exceeded/)

    expect(loadWorkspace(dataRoot, 'workspace-a')).toMatchObject({ revision: before.revision })
    expect(fs.existsSync(path.join(root, 'runs', '_failed'))).toBe(false)
    expect(workspaceLogicalBytes(root)).toBe(usedBefore)
  })

  it('does not publish when the source artifact changes during conversion', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const runner = successfulRunner({
      stdout: 'conversion output',
      stderr: 'conversion diagnostics',
      beforeWrite: () => {
        const latest = loadWorkspace(dataRoot, 'workspace-a')
        latest.artifacts[0].file = 'files/replaced.pdb'
        fs.writeFileSync(path.join(workspaceRoot(dataRoot, 'workspace-a'), 'files', 'replaced.pdb'), 'END\n')
        saveWorkspace(dataRoot, latest)
      },
    })

    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, runner))
      .rejects.toMatchObject({ statusCode: 409, code: 'SOURCE_ARTIFACT_CHANGED' })

    expect(loadWorkspace(dataRoot, 'workspace-a').artifacts).toHaveLength(1)
    const failedRoot = path.join(workspaceRoot(dataRoot, 'workspace-a'), 'runs', '_failed')
    const failedRun = path.join(failedRoot, fs.readdirSync(failedRoot)[0])
    expect(fs.readFileSync(path.join(failedRun, 'stdout.log'), 'utf8')).toBe('conversion output')
    expect(fs.readFileSync(path.join(failedRun, 'stderr.log'), 'utf8')).toBe('conversion diagnostics')
    expect(fs.existsSync(path.join(failedRun, 'report.json'))).toBe(true)
  })

  it('executes against a private snapshot and rejects a concurrently changed source', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const root = workspaceRoot(dataRoot, 'workspace-a')
    const source = path.join(root, 'files', 'input.pdb')
    const original = fs.readFileSync(source)
    let runnerInput = ''
    let runnerBytes = Buffer.alloc(0)
    const delegate = successfulRunner()
    const runner = async (...args: Parameters<typeof delegate>) => {
      runnerInput = args[1][0]
      runnerBytes = fs.readFileSync(runnerInput)
      fs.writeFileSync(source, 'END\n')
      return delegate(...args)
    }

    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, runner))
      .rejects.toMatchObject({ statusCode: 409, code: 'SOURCE_ARTIFACT_CHANGED' })

    expect(runnerInput).not.toBe(source)
    expect(path.basename(runnerInput)).toBe('.source.pdb')
    expect(runnerBytes).toEqual(original)
    const failedRoot = path.join(root, 'runs', '_failed')
    const failedRun = path.join(failedRoot, fs.readdirSync(failedRoot)[0])
    expect(fs.existsSync(path.join(failedRun, '.source.pdb'))).toBe(false)
  })

  it('deletes failure diagnostics that would leave the workspace over quota', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const root = workspaceRoot(dataRoot, 'workspace-a')
    initializeStorageQuota({
      maxUploadBytes: DEFAULT_MAX_UPLOAD_BYTES,
      workspaceQuotaBytes: workspaceLogicalBytes(root) + 256,
    })
    const runner = successfulRunner({
      stderr: 'x'.repeat(512),
      beforeWrite: () => {
        const latest = loadWorkspace(dataRoot, 'workspace-a')
        latest.artifacts[0].file = 'files/replaced.pdb'
        fs.writeFileSync(path.join(root, 'files', 'replaced.pdb'), 'END\n')
        saveWorkspace(dataRoot, latest)
      },
    })

    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, runner))
      .rejects.toMatchObject({ code: 'SOURCE_ARTIFACT_CHANGED' })

    expect(fs.readdirSync(path.join(root, 'runs'))).toEqual([])
  })

  it('maps a stable CLI conversion error without registering an artifact', async () => {
    const dataRoot = temp()
    const before = workspace(dataRoot)
    const runner = async (_command: string, args: string[]) => {
      const reportFile = args[args.indexOf('--report-json') + 1]
      const output = args[args.indexOf('-o') + 1]
      fs.writeFileSync(reportFile, JSON.stringify({
        schemaVersion: 1, operation: 'pdb-force-field-naming', status: 'error',
        tool: { name: 'dvbfixer', version: '0.8.5' },
        request: { targetForceField: 'amber', profile: 'gromacs', dryRun: false, variantOverrides: [] },
        output: { path: output, written: false, bytes: null, sha256: null },
        result: null,
        error: { code: 'NAMING_COLLISION', category: 'conversion', message: 'collision', details: {} },
      }))
      return { code: 2, stdout: '', stderr: 'collision' }
    }

    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, runner))
      .rejects.toMatchObject({ statusCode: 422, code: 'NAMING_COLLISION' })
    expect(loadWorkspace(dataRoot, 'workspace-a')).toMatchObject({ revision: before.revision })
  })

  it('rejects oversized and contradictory CLI reports', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const previousLimit = process.env.DVBFIXER_NAMING_MAX_REPORT_BYTES
    process.env.DVBFIXER_NAMING_MAX_REPORT_BYTES = '64'
    try {
      const oversized = async (_command: string, args: string[]) => {
        fs.writeFileSync(args[args.indexOf('--report-json') + 1], 'x'.repeat(65))
        return { code: 0, stdout: '', stderr: '' }
      }
      await expect(executeNamingConversion(dataRoot, 'workspace-a', request, oversized))
        .rejects.toMatchObject({ code: 'INVALID_CLI_REPORT' })
    } finally {
      if (previousLimit === undefined) delete process.env.DVBFIXER_NAMING_MAX_REPORT_BYTES
      else process.env.DVBFIXER_NAMING_MAX_REPORT_BYTES = previousLimit
    }

    const contradictory = async (_command: string, args: string[]) => {
      const output = args[args.indexOf('-o') + 1]
      const outputBytes = Buffer.from('END\n')
      fs.writeFileSync(output, outputBytes)
      const digest = await import('node:crypto').then(({ default: crypto }) =>
        crypto.createHash('sha256').update(outputBytes).digest('hex'))
      fs.writeFileSync(args[args.indexOf('--report-json') + 1], JSON.stringify({
        schemaVersion: 1, operation: 'pdb-force-field-naming', status: 'success',
        tool: { name: 'dvbfixer', version: '0.8.5' },
        request: { targetForceField: 'amber', profile: 'gromacs', dryRun: false, variantOverrides: [] },
        output: { path: output, written: true, bytes: outputBytes.length, sha256: digest },
        result: {
          model: 1, summary: { changedAtoms: 0, changedResidues: 0, variantChanges: 0, atomNameChanges: 0 },
          changes: [], diagnostics: [],
        },
        error: { code: 'IMPOSSIBLE', category: 'conversion', message: 'contradiction', details: {} },
      }))
      return { code: 0, stdout: '', stderr: '' }
    }
    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, contradictory))
      .rejects.toMatchObject({ code: 'INVALID_CLI_REPORT' })
  })

  it('reports queue saturation before attempting to parse a CLI report', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, async () => ({
      code: -1, stdout: '', stderr: 'DVBfixer process queue is full',
      started: false, failure: 'overloaded' as const,
    }))).rejects.toMatchObject({ statusCode: 503, code: 'SERVER_BUSY' })
  })

  it('classifies timeouts before report parsing and retains private diagnostics', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const previousTimeout = process.env.DVBFIXER_NAMING_TIMEOUT_MS
    process.env.DVBFIXER_NAMING_TIMEOUT_MS = '123'
    let observedTimeout: number | undefined
    try {
      await expect(executeNamingConversion(
        dataRoot,
        'workspace-a',
        { ...request, variantOverrides: [{
          chainId: 'A', residueNumber: '1', insertionCode: '', variant: 'HIE',
        }] },
        async (_command, _args, _cwd, options) => {
          observedTimeout = options.timeoutMs
          return {
            code: -1, stdout: 'partial output', stderr: 'timed out',
            started: true, failure: 'timeout' as const,
          }
        },
      )).rejects.toMatchObject({ statusCode: 504, code: 'NAMING_TIMEOUT' })
    } finally {
      if (previousTimeout === undefined) delete process.env.DVBFIXER_NAMING_TIMEOUT_MS
      else process.env.DVBFIXER_NAMING_TIMEOUT_MS = previousTimeout
    }

    expect(observedTimeout).toBe(123)
    const root = workspaceRoot(dataRoot, 'workspace-a')
    const failedRoot = path.join(root, 'runs', '_failed')
    const failedRun = path.join(failedRoot, fs.readdirSync(failedRoot)[0])
    expect(fs.readFileSync(path.join(failedRun, 'stdout.log'), 'utf8')).toBe('partial output')
    expect(fs.readFileSync(path.join(failedRun, 'stderr.log'), 'utf8')).toBe('timed out')
    expect(fs.existsSync(path.join(failedRun, 'variant-overrides.json'))).toBe(true)
    if (process.platform !== 'win32') {
      expect(fs.statSync(failedRoot).mode & 0o777).toBe(0o700)
      expect(fs.statSync(failedRun).mode & 0o777).toBe(0o700)
      expect(fs.statSync(path.join(failedRun, 'stdout.log')).mode & 0o777).toBe(0o600)
      expect(fs.statSync(path.join(failedRun, 'stderr.log')).mode & 0o777).toBe(0o600)
      expect(fs.statSync(path.join(failedRun, 'variant-overrides.json')).mode & 0o777).toBe(0o600)
    }
    expect(loadWorkspace(dataRoot, 'workspace-a').artifacts).toHaveLength(1)
  })

  it('rejects timeout settings above the Node timer range before execution', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const previousTimeout = process.env.DVBFIXER_NAMING_TIMEOUT_MS
    process.env.DVBFIXER_NAMING_TIMEOUT_MS = '2147483648'
    let ran = false
    try {
      await expect(executeNamingConversion(dataRoot, 'workspace-a', request, async () => {
        ran = true
        return { code: 0, stdout: '', stderr: '', started: true }
      })).rejects.toThrow('DVBFIXER_NAMING_TIMEOUT_MS must be at most 2147483647')
    } finally {
      if (previousTimeout === undefined) delete process.env.DVBFIXER_NAMING_TIMEOUT_MS
      else process.env.DVBFIXER_NAMING_TIMEOUT_MS = previousTimeout
    }
    expect(ran).toBe(false)
  })

  it('accepts PDB extensions and rejects unsupported artifact types before execution', async () => {
    const dataRoot = temp()
    let manifest = workspace(dataRoot)
    const root = workspaceRoot(dataRoot, 'workspace-a')
    fs.renameSync(path.join(root, 'files', 'input.pdb'), path.join(root, 'files', 'input.ENT'))
    manifest.artifacts[0].file = 'files/input.ENT'
    manifest = saveWorkspace(dataRoot, manifest)
    let runs = 0
    const runner = async (...args: Parameters<ReturnType<typeof successfulRunner>>) => {
      runs += 1
      return successfulRunner()(...args)
    }

    await executeNamingConversion(dataRoot, 'workspace-a', request, runner)
    expect(runs).toBe(1)

    manifest = loadWorkspace(dataRoot, 'workspace-a')
    manifest.artifacts[0].kind = 'artifact'
    saveWorkspace(dataRoot, manifest)
    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, runner))
      .rejects.toMatchObject({ statusCode: 415, code: 'UNSUPPORTED_SOURCE_FORMAT' })

    manifest = loadWorkspace(dataRoot, 'workspace-a')
    manifest.artifacts[0].kind = 'structure'
    manifest.artifacts[0].file = 'files/input.cif'
    fs.writeFileSync(path.join(root, 'files', 'input.cif'), 'data_test\n')
    saveWorkspace(dataRoot, manifest)
    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, runner))
      .rejects.toMatchObject({ statusCode: 415, code: 'UNSUPPORTED_SOURCE_FORMAT' })
    expect(runs).toBe(1)
  })

  it('enforces the source limit before invoking the runner', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const source = path.join(workspaceRoot(dataRoot, 'workspace-a'), 'files', 'input.pdb')
    const sourceBytes = fs.statSync(source).size
    const previousLimit = process.env.DVBFIXER_NAMING_MAX_SOURCE_BYTES
    let runs = 0
    const runner = async (...args: Parameters<ReturnType<typeof successfulRunner>>) => {
      runs += 1
      return successfulRunner()(...args)
    }
    try {
      process.env.DVBFIXER_NAMING_MAX_SOURCE_BYTES = String(sourceBytes)
      await executeNamingConversion(dataRoot, 'workspace-a', request, runner)
      process.env.DVBFIXER_NAMING_MAX_SOURCE_BYTES = String(sourceBytes - 1)
      await expect(executeNamingConversion(dataRoot, 'workspace-a', request, runner))
        .rejects.toMatchObject({ statusCode: 413, code: 'SOURCE_TOO_LARGE' })
    } finally {
      if (previousLimit === undefined) delete process.env.DVBFIXER_NAMING_MAX_SOURCE_BYTES
      else process.env.DVBFIXER_NAMING_MAX_SOURCE_BYTES = previousLimit
    }
    expect(runs).toBe(1)
  })

  it('rejects generated output above the source-size limit before reading it', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const root = workspaceRoot(dataRoot, 'workspace-a')
    const sourceBytes = fs.statSync(path.join(root, 'files', 'input.pdb')).size
    const previousLimit = process.env.DVBFIXER_NAMING_MAX_SOURCE_BYTES
    process.env.DVBFIXER_NAMING_MAX_SOURCE_BYTES = String(sourceBytes)
    try {
      await expect(executeNamingConversion(
        dataRoot,
        'workspace-a',
        request,
        successfulRunner({ outputBytes: Buffer.alloc(sourceBytes + 1, 'x') }),
      )).rejects.toMatchObject({ statusCode: 500, code: 'OUTPUT_TOO_LARGE' })
    } finally {
      if (previousLimit === undefined) delete process.env.DVBFIXER_NAMING_MAX_SOURCE_BYTES
      else process.env.DVBFIXER_NAMING_MAX_SOURCE_BYTES = previousLimit
    }
    const failedRoot = path.join(root, 'runs', '_failed')
    const failedRun = path.join(failedRoot, fs.readdirSync(failedRoot)[0])
    expect(fs.existsSync(path.join(failedRun, '.source.pdb'))).toBe(false)
    expect(loadWorkspace(dataRoot, 'workspace-a').artifacts).toHaveLength(1)
  })

  it.each([
    ['regular', false], ['dangling', false], ['regular', true], ['dangling', true],
  ] as const)('rejects a child-created %s output symlink without retaining it (dryRun=%s)', async (target, dryRun) => {
    const dataRoot = temp()
    workspace(dataRoot)
    const root = workspaceRoot(dataRoot, 'workspace-a')
    const outside = path.join(temp(), 'outside.pdb')
    const content = 'END\n'
    if (target === 'regular') fs.writeFileSync(outside, content)

    await expect(executeNamingConversion(
      dataRoot, 'workspace-a', { ...request, dryRun }, successfulRunner({ outputSymlink: outside, dryRun }),
    )).rejects.toMatchObject({ statusCode: 500, code: 'UNSAFE_OUTPUT' })

    if (target === 'regular') expect(fs.readFileSync(outside, 'utf8')).toBe(content)
    const failedRoot = path.join(root, 'runs', '_failed')
    const failedRun = path.join(failedRoot, fs.readdirSync(failedRoot)[0])
    expect(() => fs.lstatSync(path.join(failedRun, 'named.pdb'))).toThrow()
    expect(loadWorkspace(dataRoot, 'workspace-a').artifacts).toHaveLength(1)
  })

  it('rejects source symlinks that escape the workspace', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const source = path.join(workspaceRoot(dataRoot, 'workspace-a'), 'files', 'input.pdb')
    const outside = path.join(temp(), 'outside.pdb')
    fs.writeFileSync(outside, 'END\n')
    fs.unlinkSync(source)
    fs.symlinkSync(outside, source)

    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, successfulRunner()))
      .rejects.toMatchObject({ statusCode: 404, code: 'ARTIFACT_NOT_FOUND' })
  })

  it.each(['child-error', 'malformed-report'] as const)('removes dangling output links before retaining %s diagnostics', async failure => {
    const dataRoot = temp()
    workspace(dataRoot)
    const root = workspaceRoot(dataRoot, 'workspace-a')
    const outside = path.join(temp(), 'missing.pdb')
    const base = successfulRunner({ outputSymlink: outside })
    const runner = async (...args: Parameters<typeof base>) => {
      const result = await base(...args)
      if (failure === 'child-error') return { ...result, code: 1 }
      fs.writeFileSync(args[1][args[1].indexOf('--report-json') + 1], '{invalid')
      return result
    }
    await expect(executeNamingConversion(dataRoot, 'workspace-a', request, runner))
      .rejects.toMatchObject({ statusCode: 500, code: failure === 'child-error' ? 'SUBPROCESS_FAILED' : 'INVALID_CLI_REPORT' })
    const failedRoot = path.join(root, 'runs', '_failed')
    const failedRun = path.join(failedRoot, fs.readdirSync(failedRoot)[0])
    expect(() => fs.lstatSync(path.join(failedRun, 'named.pdb'))).toThrow()
    expect(fs.existsSync(outside)).toBe(false)
    expect(loadWorkspace(dataRoot, 'workspace-a').artifacts).toHaveLength(1)
  })

  it('rejects an artifact ID belonging to another workspace', async () => {
    const dataRoot = temp()
    workspace(dataRoot, 'workspace-a')
    const other = workspace(dataRoot, 'workspace-b')
    other.artifacts[0].id = 'other-source'
    saveWorkspace(dataRoot, other)

    await expect(executeNamingConversion(
      dataRoot, 'workspace-a', { ...request, inputArtifactId: 'other-source' }, successfulRunner(),
    )).rejects.toMatchObject({ statusCode: 404, code: 'ARTIFACT_NOT_FOUND' })
  })
})

describe('naming API transport contract', () => {
  it('returns 507 and deletes generated data when publication exhausts quota', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const root = workspaceRoot(dataRoot, 'workspace-a')
    const usedBefore = workspaceLogicalBytes(root)
    initializeStorageQuota({
      maxUploadBytes: DEFAULT_MAX_UPLOAD_BYTES,
      workspaceQuotaBytes: usedBefore + 256,
    })

    const response = await apiRequest(
      dataRoot,
      'POST',
      '/workspaces/workspace-a/naming-conversions',
      JSON.stringify(request),
      'application/json',
      successfulRunner(),
    )

    expect(response).toMatchObject({
      status: 507,
      body: { error: { code: 'WORKSPACE_QUOTA_EXCEEDED' } },
    })
    expect(workspaceLogicalBytes(root)).toBe(usedBefore)
    expect(fs.existsSync(path.join(root, 'runs', '_failed'))).toBe(false)
  })

  it('executes a valid request and returns the registered artifact', async () => {
    const dataRoot = temp()
    workspace(dataRoot)
    const response = await apiRequest(
      dataRoot,
      'POST',
      '/workspaces/workspace-a/naming-conversions',
      JSON.stringify(request),
      'application/json',
      successfulRunner(),
    )
    expect(response.status).toBe(201)
    expect(response.body).toMatchObject({ status: 'succeeded', sourceArtifactId: 'source' })
    expect(response.body.outputArtifact.file).toMatch(/^runs\/naming_/)
    const saved = loadWorkspace(dataRoot, 'workspace-a')
    expect(saved.artifacts).toHaveLength(2)
    expect(saved.artifacts[1].namingProvenance?.serviceVersion).toBe('test-service')
  })

  it('publishes OpenAPI from the runtime request schema', async () => {
    const response = await apiRequest(temp(), 'GET', '/openapi.json')
    expect(response.status).toBe(200)
    expect(response.body).toEqual(JSON.parse(JSON.stringify(NAMING_OPENAPI_DOCUMENT)))
    const publishedExample = NAMING_OPENAPI_DOCUMENT
      .paths['/api/v1/workspaces/{workspaceId}/naming-conversions']
      .post.requestBody.content['application/json'].example
    expect(publishedExample).toEqual(NAMING_REQUEST_EXAMPLE)
    expect(Value.Check(NamingConversionRequestSchema, publishedExample)).toBe(true)
    expect(NAMING_OPENAPI_DOCUMENT.components.securitySchemes.bearerAuth).toEqual({
      type: 'http', scheme: 'bearer',
    })
    expect(NAMING_OPENAPI_DOCUMENT.paths['/api/v1/workspaces/{workspaceId}/naming-conversions']
      .post.security).toEqual([{ bearerAuth: [] }])
  })

  it('rejects unsupported media types and malformed or unknown request fields', async () => {
    const dataRoot = temp()
    const media = await apiRequest(dataRoot, 'POST', '/workspaces/workspace-a/naming-conversions', '{}', 'text/plain')
    expect(media.status).toBe(415)
    expect(media.body.error.code).toBe('UNSUPPORTED_MEDIA_TYPE')
    expect(media.headers['x-request-id']).toMatch(/^req_/)

    const malformed = await apiRequest(dataRoot, 'POST', '/workspaces/workspace-a/naming-conversions', '{')
    expect(malformed.status).toBe(400)
    expect(malformed.body.error.code).toBe('INVALID_JSON')

    const unknown = await apiRequest(dataRoot, 'POST', '/workspaces/workspace-a/naming-conversions', JSON.stringify({
      ...request, unexpected: true,
    }))
    expect(unknown.status).toBe(400)
    expect(unknown.body.error.code).toBe('INVALID_REQUEST')
  })

  it('returns the V1 error envelope for an oversized request body', async () => {
    const response = await apiRequest(
      temp(), 'POST', '/workspaces/workspace-a/naming-conversions', 'x'.repeat(2 * 1024 * 1024 + 1),
    )
    expect(response.status).toBe(413)
    expect(response.body.error.code).toBe('PAYLOAD_TOO_LARGE')
    expect(response.body.error.requestId).toMatch(/^req_/)
  })
})
