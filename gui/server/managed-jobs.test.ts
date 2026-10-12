import { afterEach, describe, expect, it } from 'vitest'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { Readable } from 'node:stream'
import {
  cancelManagedJob, createManagedJob, getManagedJob, listManagedJobs, registerManagedJobApi,
  type ManagedJobRecord,
} from './managed-jobs'
import {
  createWorkspace, ensureWorkspaceMigration, listWorkspaces, loadWorkspace, saveWorkspace, workspaceRoot,
} from './workspace-api'
import {
  DEFAULT_MAX_UPLOAD_BYTES, DEFAULT_WORKSPACE_QUOTA_BYTES, initializeStorageQuota,
  workspaceLogicalBytes,
} from './storage-quota'

const directories: string[] = []
const originalEnvironment = {
  executable: process.env.DVBFIXER_EXECUTABLE,
  args: process.env.DVBFIXER_ARGS,
}

async function apiRequest(dataRoot: string, method: string, url: string, body = '', contentType = 'application/json') {
  let middleware: ((req: any, res: any, next: () => void) => Promise<void>) | undefined
  const server = { middlewares: { use: (_route: string, handler: typeof middleware) => { middleware = handler } } }
  registerManagedJobApi(server as any, dataRoot)
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
  return { status: response.statusCode, headers, body: responseBody ? JSON.parse(responseBody) : null }
}

function root(): string {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'dvbfixer-managed-jobs-'))
  directories.push(directory)
  ensureWorkspaceMigration(directory)
  return directory
}

function useNode(script: string): void {
  process.env.DVBFIXER_EXECUTABLE = process.execPath
  process.env.DVBFIXER_ARGS = JSON.stringify(['-e', script])
}

async function terminal(
  dataRoot: string,
  workspaceId: string,
  jobId: string,
  timeout = 3000,
): Promise<ManagedJobRecord> {
  const deadline = Date.now() + timeout
  while (Date.now() < deadline) {
    const record = getManagedJob(dataRoot, workspaceId, jobId)
    if (['succeeded', 'failed', 'cancelled'].includes(record.status)) return record
    await new Promise(resolve => setTimeout(resolve, 10))
  }
  throw new Error(`job ${jobId} did not finish`)
}

afterEach(() => {
  initializeStorageQuota({
    maxUploadBytes: DEFAULT_MAX_UPLOAD_BYTES,
    workspaceQuotaBytes: DEFAULT_WORKSPACE_QUOTA_BYTES,
  })
  for (const [key, value] of Object.entries({
    DVBFIXER_EXECUTABLE: originalEnvironment.executable,
    DVBFIXER_ARGS: originalEnvironment.args,
  })) {
    if (value === undefined) delete process.env[key]
    else process.env[key] = value
  }
  for (const directory of directories.splice(0)) fs.rmSync(directory, { recursive: true, force: true })
})

describe('managed DVBfixer jobs', () => {
  it.each([true, false])('archives native diffusion output without auto-loading rejected candidates (passed=%s)', async passed => {
    const dataRoot = root()
    const workspace = listWorkspaces(dataRoot)[0]
    fs.writeFileSync(path.join(workspaceRoot(dataRoot, workspace.id), 'input.pdb'), 'END\n')
    useNode(`
      const fs=require('node:fs'), path=require('node:path'), crypto=require('node:crypto');
      const out=process.argv[process.argv.indexOf('-o')+1]; fs.mkdirSync(out,{recursive:true});
      const references={};
      for(const label of ['pdb','dat','provenance','sampler_trace']) {
        const name='ranked-first.'+label; fs.writeFileSync(path.join(out,name),label);
        references[label]={path:name,sha256:crypto.createHash('sha256').update(label).digest('hex')};
      }
      fs.writeFileSync(path.join(out,'bundle.json'),JSON.stringify({schema_version:2,status:${JSON.stringify(passed ? 'success' : 'validation_failed')},
        candidates:[{candidate_id:'ranked-first',validation_passed:${passed},...references}]}));
    `)
    const created = createManagedJob(dataRoot, {
      workspaceId: workspace.id, command: 'model', inputFile: 'input.pdb', values: { '--backend': 'diffusion' },
    })
    const finished = await terminal(dataRoot, workspace.id, created.id)
    expect(finished.status).toBe('succeeded')
    expect(finished.outputFile).toBe(passed ? `${finished.outputDir}/result/ranked-first.pdb` : null)
    expect(finished.args).toContain('--diffusion-work-parent')
    const temporary = finished.args[finished.args.indexOf('--diffusion-work-parent') + 1]
    expect(fs.existsSync(temporary)).toBe(false)
    expect(loadWorkspace(dataRoot, workspace.id).artifacts.some(artifact => artifact.file.endsWith('/bundle.json'))).toBe(true)
    if (passed) {
      const immutable = path.join(workspaceRoot(dataRoot, workspace.id), finished.outputDir, 'result')
      const before = Object.fromEntries(fs.readdirSync(immutable).map(file => [file, fs.readFileSync(path.join(immutable, file), 'utf8')]))
      useNode(`
        const fs=require('node:fs'); const input=process.argv[2];
        if(!input.includes('_input_') || !fs.existsSync(input.replace(/\\.pdb$/,'.dat'))) process.exit(2);
        fs.writeFileSync(process.argv[process.argv.indexOf('-o')+1],fs.readFileSync(input));
      `)
      const next = createManagedJob(dataRoot, {
        workspaceId: workspace.id, command: 'prepare', inputFile: finished.outputFile!,
      })
      const prepared = await terminal(dataRoot, workspace.id, next.id)
      expect(prepared.status).toBe('succeeded')
      expect(prepared.outputFile).not.toContain('_input_')
      expect(Object.fromEntries(fs.readdirSync(immutable).map(file => [file, fs.readFileSync(path.join(immutable, file), 'utf8')]))).toEqual(before)
    }
  })
  it('exposes versioned workspace routes with the common error envelope', async () => {
    const dataRoot = root()
    const workspace = listWorkspaces(dataRoot)[0]
    const base = `/workspaces/${workspace.id}/jobs`

    const media = await apiRequest(dataRoot, 'POST', base, '{}', 'text/plain')
    expect(media.status).toBe(415)
    expect(media.body.error).toMatchObject({ code: 'UNSUPPORTED_MEDIA_TYPE' })
    expect(media.body.error.requestId).toMatch(/^req_/)

    const malformed = await apiRequest(dataRoot, 'POST', base, '{')
    expect(malformed.status).toBe(400)
    expect(malformed.body.error.code).toBe('INVALID_JSON')

    const unsupported = await apiRequest(dataRoot, 'POST', base, JSON.stringify({ command: 'unknown' }))
    expect(unsupported.status).toBe(422)
    expect(unsupported.body.error.code).toBe('UNSUPPORTED_OPERATION')

    const listed = await apiRequest(dataRoot, 'GET', base)
    expect(listed.status).toBe(200)
    expect(listed.body).toEqual([])
  })

  it('reports a missing command clearly', () => {
    const dataRoot = root()
    const workspace = listWorkspaces(dataRoot)[0]
    expect(() => createManagedJob(dataRoot, {
      workspaceId: workspace.id,
      command: undefined as unknown as string,
    })).toThrow('command is required')
  })

  it('persists a successful fake-CLI lifecycle and logs', async () => {
    const dataRoot = root()
    const workspace = listWorkspaces(dataRoot)[0]
    useNode("console.log('managed ok')")
    const created = createManagedJob(dataRoot, { workspaceId: workspace.id, command: 'doctor' })
    expect(created.status).toBe('queued')
    expect(created.id).toMatch(/^[0-9a-f-]{36}$/)

    const finished = await terminal(dataRoot, workspace.id, created.id)
    expect(finished.status).toBe('succeeded')
    expect(finished.startedAt).toBeTruthy()
    expect(finished.finishedAt).toBeTruthy()
    expect(finished.exitCode).toBe(0)
    expect(finished.args).toEqual([])
    const workspaceDirectory = workspaceRoot(dataRoot, workspace.id)
    expect(fs.readFileSync(path.join(workspaceDirectory, finished.stdoutLog), 'utf8')).toContain('managed ok')
    expect(fs.existsSync(path.join(workspaceDirectory, finished.outputDir, 'job.json'))).toBe(true)
    expect(listManagedJobs(dataRoot, workspace.id).map(job => job.id)).toContain(created.id)
    expect(finished.provenance).toMatchObject({
      apiVersion: 1, command: 'doctor', serviceVersion: 'unknown',
      request: { inputs: {}, values: {}, fastaSha256: null },
      resolvedInputs: [],
    })
    expect(finished.provenance!.outputs).toHaveLength(1)
  })

  it('records reproducible input and output artifact provenance', async () => {
    const dataRoot = root()
    const workspace = listWorkspaces(dataRoot)[0]
    const inputFile = path.join(workspaceRoot(dataRoot, workspace.id), 'files', 'input.pdb')
    fs.mkdirSync(path.dirname(inputFile), { recursive: true })
    fs.writeFileSync(inputFile, 'END\n')
    saveWorkspace(dataRoot, {
      ...loadWorkspace(dataRoot, workspace.id),
      artifacts: [{ id: 'source-id', file: 'files/input.pdb', name: 'input.pdb', kind: 'structure' }],
    })
    useNode("const fs=require('node:fs');const i=process.argv.indexOf('-o');fs.writeFileSync(process.argv[i+1],'END\\n')")

    const created = createManagedJob(dataRoot, {
      workspaceId: workspace.id,
      command: 'renumber',
      inputs: { input: 'files/input.pdb' },
      values: { '--number-from-1': true },
    }, 'local', '9.9.9')
    const finished = await terminal(dataRoot, workspace.id, created.id)

    expect(finished.status).toBe('succeeded')
    expect(finished.provenance).toMatchObject({
      serviceVersion: '9.9.9', dvbfixerVersion: '9.9.9',
      request: {
        inputs: { input: 'files/input.pdb' },
        values: { '--number-from-1': true },
      },
      resolvedInputs: [{ artifactId: 'source-id', file: 'files/input.pdb' }],
    })
    expect(finished.provenance!.resolvedInputs[0].sha256).toMatch(/^[a-f0-9]{64}$/)
    expect(finished.provenance!.outputs).toHaveLength(1)
    const artifact = loadWorkspace(dataRoot, workspace.id).artifacts
      .find(candidate => candidate.id === finished.provenance!.outputs[0].artifactId)!
    expect(artifact.workflowProvenance?.outputs[0].sha256)
      .toBe(finished.provenance!.outputs[0].sha256)
  })

  it('publishes diagnose findings when the CLI uses its documented exit code 1', async () => {
    const dataRoot = root()
    const workspace = listWorkspaces(dataRoot)[0]
    const input = path.join(workspaceRoot(dataRoot, workspace.id), 'input.pdb')
    fs.writeFileSync(input, 'END\n')
    useNode("const fs=require('node:fs');const i=process.argv.indexOf('-o');fs.writeFileSync(process.argv[i+1],'finding\\n');process.exit(1)")
    const created = createManagedJob(dataRoot, {
      workspaceId: workspace.id, command: 'diagnose', inputFile: 'input.pdb',
    })
    const finished = await terminal(dataRoot, workspace.id, created.id)
    expect(finished).toMatchObject({ status: 'succeeded', exitCode: 1 })
    expect(finished.outputFile).toMatch(/\.txt$/)
    expect(finished.provenance!.outputs).toHaveLength(1)
  })

  it('rejects concurrent jobs in one workspace and cancels the active process', async () => {
    const dataRoot = root()
    const workspace = listWorkspaces(dataRoot)[0]
    useNode('setInterval(() => {}, 1000)')
    const created = createManagedJob(dataRoot, { workspaceId: workspace.id, command: 'doctor' })
    expect(() => createManagedJob(dataRoot, { workspaceId: workspace.id, command: 'doctor' }))
      .toThrow(/already running/)
    cancelManagedJob(dataRoot, workspace.id, created.id)
    const finished = await terminal(dataRoot, workspace.id, created.id)
    expect(finished.status).toBe('cancelled')
    expect(finished.finishedAt).toBeTruthy()
    expect(fs.readFileSync(path.join(workspaceRoot(dataRoot, workspace.id), finished.stderrLog), 'utf8'))
      .toContain('cancelled')
  })

  it('does not publish outputs after the initiating writer loses access', async () => {
    const dataRoot = root()
    const workspace = saveWorkspace(dataRoot, {
      ...createWorkspace(dataRoot, 'Secured', 'owner'),
      acl: [{ principalId: 'writer', role: 'writer' }],
      artifacts: [{ id: 'input', file: 'files/input.pdb', name: 'input.pdb', kind: 'structure' }],
    })
    const input = path.join(workspaceRoot(dataRoot, workspace.id), 'files', 'input.pdb')
    fs.mkdirSync(path.dirname(input), { recursive: true })
    fs.writeFileSync(input, 'END\n')
    useNode("const fs=require('node:fs');const i=process.argv.indexOf('-o');setTimeout(()=>fs.writeFileSync(process.argv[i+1],'END\\n'),100)")
    const created = createManagedJob(dataRoot, {
      workspaceId: workspace.id, command: 'renumber', inputs: { input: 'files/input.pdb' },
    }, 'writer')
    const latest = loadWorkspace(dataRoot, workspace.id)
    saveWorkspace(dataRoot, { ...latest, acl: [] })

    const finished = await terminal(dataRoot, workspace.id, created.id)
    expect(finished.status).toBe('failed')
    expect(finished.error).toContain('workspace not found')
    expect(loadWorkspace(dataRoot, workspace.id).artifacts).toHaveLength(1)
  })

  it('removes generated payloads when a child exceeds the workspace quota', async () => {
    const dataRoot = root()
    const workspace = listWorkspaces(dataRoot)[0]
    const workspaceDirectory = workspaceRoot(dataRoot, workspace.id)
    initializeStorageQuota({
      maxUploadBytes: DEFAULT_MAX_UPLOAD_BYTES,
      workspaceQuotaBytes: workspaceLogicalBytes(workspaceDirectory) + 70 * 1024,
    })
    useNode("require('node:fs').writeFileSync('large.pdb','x'.repeat(100*1024))")

    const created = createManagedJob(dataRoot, { workspaceId: workspace.id, command: 'doctor' })
    const finished = await terminal(dataRoot, workspace.id, created.id)

    expect(finished.status).toBe('failed')
    expect(finished.error).toContain('workspace quota exceeded')
    const files = fs.readdirSync(path.join(workspaceDirectory, finished.outputDir), { recursive: true })
    expect(files.some(file => String(file).endsWith('.pdb'))).toBe(false)
  })

  it('does not acquire the workspace run lock when quota admission fails', async () => {
    const dataRoot = root()
    const workspace = listWorkspaces(dataRoot)[0]
    const workspaceDirectory = workspaceRoot(dataRoot, workspace.id)
    initializeStorageQuota({
      maxUploadBytes: DEFAULT_MAX_UPLOAD_BYTES,
      workspaceQuotaBytes: workspaceLogicalBytes(workspaceDirectory) + 1,
    })
    expect(() => createManagedJob(dataRoot, { workspaceId: workspace.id, command: 'doctor' }))
      .toThrow(/workspace quota exceeded/)

    initializeStorageQuota({
      maxUploadBytes: DEFAULT_MAX_UPLOAD_BYTES,
      workspaceQuotaBytes: DEFAULT_WORKSPACE_QUOTA_BYTES,
    })
    useNode('process.exit(0)')
    const accepted = createManagedJob(dataRoot, { workspaceId: workspace.id, command: 'doctor' })
    await expect(terminal(dataRoot, workspace.id, accepted.id)).resolves.toMatchObject({ status: 'succeeded' })
  })
})
