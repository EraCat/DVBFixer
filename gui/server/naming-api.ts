import type { IncomingMessage, ServerResponse } from 'node:http'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { Value } from '@sinclair/typebox/value'
import type { ApiRouteHost } from './http-types'
import {
  ApiErrorSchema,
  NAMING_OPENAPI_DOCUMENT,
  NamingCliReportSchema,
  NamingConversionRequestSchema,
  NamingConversionResponseSchema,
  type NamingCliReport,
  type NamingConversionRequest,
  type NamingConversionResponse,
} from './naming-api-schema'
import { runDvbfixerArgs } from './dvbfixer-runner'
import { errorStatus, readRequestBody } from './request-body'
import { ensureRequestId } from './request-observability'
import {
  DEFAULT_NAMING_FAILED_MAX_AGE_HOURS,
  DEFAULT_NAMING_FAILED_MAX_RUNS,
  namingFailureDirectory,
  pruneNamingFailures,
  type NamingFailureRetention,
} from './naming-retention'
import { assertWorkspaceQuota, WorkspaceQuotaExceededError } from './storage-quota'
import { acquireWorkspaceRunLock } from './workspace-lock'
import {
  assertWorkspaceAccess,
  loadWorkspace,
  resolveWorkspaceFile,
  updateWorkspace,
  workspaceRoot,
  writeJsonAtomic,
  type NamingConversionProvenance,
  type WorkspaceArtifact,
} from './workspace-api'

const DEFAULT_MAX_SOURCE_BYTES = 50 * 1024 * 1024
const DEFAULT_MAX_REPORT_BYTES = 20 * 1024 * 1024
const DEFAULT_TIMEOUT_MS = 60_000
const MAX_TIMEOUT_MS = 2_147_483_647
const MAX_OUTPUT_BYTES = 1024 * 1024

function positiveIntegerSetting(name: string, fallback: number, maximum = Number.MAX_SAFE_INTEGER): number {
  const value = process.env[name]
  if (value === undefined) return fallback
  if (!/^[1-9]\d*$/.test(value)) throw new Error(`${name} must be a positive integer`)
  const parsed = Number(value)
  if (!Number.isSafeInteger(parsed) || parsed > maximum) {
    throw new Error(`${name} must be at most ${maximum}`)
  }
  return parsed
}

function namingSettings(): {
  maxSourceBytes: number; maxReportBytes: number; timeoutMs: number
  failureRetention: NamingFailureRetention
} {
  return {
    maxSourceBytes: positiveIntegerSetting('DVBFIXER_NAMING_MAX_SOURCE_BYTES', DEFAULT_MAX_SOURCE_BYTES),
    maxReportBytes: positiveIntegerSetting('DVBFIXER_NAMING_MAX_REPORT_BYTES', DEFAULT_MAX_REPORT_BYTES),
    timeoutMs: positiveIntegerSetting('DVBFIXER_NAMING_TIMEOUT_MS', DEFAULT_TIMEOUT_MS, MAX_TIMEOUT_MS),
    failureRetention: {
      maxRuns: positiveIntegerSetting('DVBFIXER_NAMING_FAILED_MAX_RUNS', DEFAULT_NAMING_FAILED_MAX_RUNS),
      maxAgeHours: positiveIntegerSetting(
        'DVBFIXER_NAMING_FAILED_MAX_AGE_HOURS', DEFAULT_NAMING_FAILED_MAX_AGE_HOURS,
        Math.floor(Number.MAX_SAFE_INTEGER / 3_600_000),
      ),
    },
  }
}

type NamingRunner = typeof runDvbfixerArgs

class NamingApiError extends Error {
  readonly statusCode: number
  readonly code: string
  readonly details?: unknown

  constructor(
    statusCode: number,
    code: string,
    message: string,
    details?: unknown,
  ) {
    super(message)
    this.name = 'NamingApiError'
    this.statusCode = statusCode
    this.code = code
    this.details = details
  }
}

function sha256(content: Buffer): string {
  return crypto.createHash('sha256').update(content).digest('hex')
}

function readBoundedRegularFile(file: string, maxBytes: number): Buffer | null {
  const beforeOpen = fs.lstatSync(file)
  if (beforeOpen.isSymbolicLink() || !beforeOpen.isFile()) throw new Error('unsafe file type')
  const flags = process.platform === 'win32'
    ? fs.constants.O_RDONLY
    : fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW
  const descriptor = fs.openSync(file, flags)
  try {
    const opened = fs.fstatSync(descriptor)
    if (!opened.isFile() || opened.dev !== beforeOpen.dev || opened.ino !== beforeOpen.ino) {
      throw new Error('file changed while opening')
    }
    const chunks: Buffer[] = []
    const chunkSize = Math.min(1024 * 1024, maxBytes + 1)
    let total = 0
    while (total <= maxBytes) {
      const chunk = Buffer.allocUnsafe(chunkSize)
      const bytesRead = fs.readSync(descriptor, chunk, 0, chunk.length, null)
      if (bytesRead === 0) return Buffer.concat(chunks, total)
      total += bytesRead
      if (total > maxBytes) return null
      chunks.push(Buffer.from(chunk.subarray(0, bytesRead)))
    }
    return null
  } finally {
    fs.closeSync(descriptor)
  }
}

function replaceWithPrivateFile(file: string, content: Buffer): void {
  const temporary = path.join(path.dirname(file), `.${path.basename(file)}.validated-${crypto.randomUUID()}`)
  try {
    writePrivateFile(temporary, content)
    fs.renameSync(temporary, file)
  } finally {
    try { fs.rmSync(temporary, { force: true }) } catch { /* preserve the write or rename failure */ }
  }
}

function schemaError(schema: Parameters<typeof Value.Errors>[0], value: unknown): string {
  const first = Value.Errors(schema, value).First()
  return first ? `${first.path || '/'} ${first.message}` : 'value does not match schema'
}

function parseRequest(value: unknown): NamingConversionRequest {
  if (!Value.Check(NamingConversionRequestSchema, value)) {
    throw new NamingApiError(400, 'INVALID_REQUEST', schemaError(NamingConversionRequestSchema, value))
  }
  const identities = new Set<string>()
  for (const override of value.variantOverrides || []) {
    const identity = JSON.stringify([override.chainId, override.residueNumber, override.insertionCode])
    if (identities.has(identity)) {
      throw new NamingApiError(400, 'INVALID_REQUEST', 'variantOverrides contains a duplicate residue identity')
    }
    identities.add(identity)
  }
  return value
}

function parseReport(file: string, maxBytes: number): { report: NamingCliReport; bytes: Buffer } {
  let bytes: Buffer
  let value: unknown
  try {
    const stat = fs.statSync(file)
    if (!stat.isFile() || stat.size > maxBytes) {
      throw new NamingApiError(500, 'INVALID_CLI_REPORT', 'atom-names report is missing or exceeds the configured limit')
    }
    bytes = fs.readFileSync(file)
    value = JSON.parse(bytes.toString('utf8'))
  } catch (error) {
    if (error instanceof NamingApiError) throw error
    throw new NamingApiError(500, 'INVALID_CLI_REPORT', 'atom-names did not produce a readable JSON report')
  }
  if (!Value.Check(NamingCliReportSchema, value)) {
    throw new NamingApiError(500, 'INVALID_CLI_REPORT', schemaError(NamingCliReportSchema, value))
  }
  return { report: value, bytes }
}

function validateReportRequest(report: NamingCliReport, request: NamingConversionRequest): void {
  const overrides = request.variantOverrides || []
  if (report.request.targetForceField !== request.target.forceField ||
      report.request.profile !== request.target.profile ||
      report.request.dryRun !== (request.dryRun || false) ||
      JSON.stringify(report.request.variantOverrides) !== JSON.stringify(overrides)) {
    throw new NamingApiError(500, 'CLI_REPORT_MISMATCH', 'atom-names report does not match the API request')
  }
  if (report.status === 'success' && (!report.result || report.error !== null ||
      report.output.bytes === null || report.output.sha256 === null)) {
    throw new NamingApiError(500, 'INVALID_CLI_REPORT', 'atom-names success report is internally inconsistent')
  }
  if (report.status === 'error' && (report.result !== null || report.error === null || report.output.written)) {
    throw new NamingApiError(500, 'INVALID_CLI_REPORT', 'atom-names error report is internally inconsistent')
  }
}

function outputName(request: NamingConversionRequest, sourceFile: string): string {
  if (request.outputName) return request.outputName
  const stem = path.basename(sourceFile, path.extname(sourceFile))
  return `${stem}_${request.target.forceField}_gromacs.pdb`
}

function moveToFailureArea(operationDirectory: string, workspaceDirectory: string): void {
  if (!fs.existsSync(operationDirectory)) return
  const failed = namingFailureDirectory(workspaceDirectory)
  fs.mkdirSync(failed, { recursive: true, mode: 0o700 })
  fs.chmodSync(failed, 0o700)
  fs.chmodSync(operationDirectory, 0o700)
  const destination = path.join(failed, path.basename(operationDirectory))
  fs.renameSync(operationDirectory, destination)
  // Retention starts when the operation fails, not when its last file was written.
  const now = new Date()
  fs.utimesSync(destination, now, now)
}

function writePrivateFile(file: string, content: string | Buffer): void {
  fs.writeFileSync(file, content, { mode: 0o600 })
  fs.chmodSync(file, 0o600)
}

function removeSuccessHelpers(operationDirectory: string, output: string): void {
  for (const entry of fs.readdirSync(operationDirectory, { withFileTypes: true })) {
    const candidate = path.join(operationDirectory, entry.name)
    if (candidate === output) continue
    fs.rmSync(candidate, { recursive: entry.isDirectory(), force: true })
  }
}

export async function executeNamingConversion(
  dataRoot: string,
  workspaceId: string,
  request: NamingConversionRequest,
  runner: NamingRunner = runDvbfixerArgs,
  authorizePublication?: (workspace: ReturnType<typeof loadWorkspace>) => void,
  signal?: AbortSignal,
  serviceVersion = 'unknown',
): Promise<{ statusCode: 200 | 201; response: NamingConversionResponse }> {
  const settings = namingSettings()
  let initial
  try { initial = loadWorkspace(dataRoot, workspaceId) } catch {
    throw new NamingApiError(404, 'WORKSPACE_NOT_FOUND', 'workspace does not exist')
  }
  const sourceArtifact = initial.artifacts.find(artifact => artifact.id === request.inputArtifactId && !artifact.hidden)
  if (!sourceArtifact) throw new NamingApiError(404, 'ARTIFACT_NOT_FOUND', 'input artifact does not exist')
  if (sourceArtifact.kind !== 'structure') {
    throw new NamingApiError(415, 'UNSUPPORTED_SOURCE_FORMAT', 'input artifact is not a structure')
  }
  if (!['.pdb', '.ent'].includes(path.extname(sourceArtifact.file).toLowerCase())) {
    throw new NamingApiError(415, 'UNSUPPORTED_SOURCE_FORMAT', 'atom naming V1 accepts PDB artifacts only')
  }
  let source: string
  try { source = resolveWorkspaceFile(dataRoot, workspaceId, sourceArtifact.file) } catch {
    throw new NamingApiError(404, 'ARTIFACT_NOT_FOUND', 'input artifact file does not exist')
  }
  let sourceStat: fs.Stats
  try { sourceStat = fs.lstatSync(source) } catch {
    throw new NamingApiError(404, 'ARTIFACT_NOT_FOUND', 'input artifact file does not exist')
  }
  if (sourceStat.isSymbolicLink() || !sourceStat.isFile()) {
    throw new NamingApiError(404, 'ARTIFACT_NOT_FOUND', 'input artifact is not a file')
  }
  if (sourceStat.size > settings.maxSourceBytes) {
    throw new NamingApiError(413, 'SOURCE_TOO_LARGE', `input artifact exceeds ${settings.maxSourceBytes} bytes`)
  }
  let sourceBytes: Buffer | null
  try { sourceBytes = readBoundedRegularFile(source, settings.maxSourceBytes) } catch {
    throw new NamingApiError(404, 'ARTIFACT_NOT_FOUND', 'input artifact file does not exist')
  }
  if (!sourceBytes) {
    throw new NamingApiError(413, 'SOURCE_TOO_LARGE', `input artifact exceeds ${settings.maxSourceBytes} bytes`)
  }
  const sourceSha256 = sha256(sourceBytes)

  const operationId = crypto.randomUUID()
  const release = acquireWorkspaceRunLock(dataRoot, workspaceId)
  const root = workspaceRoot(dataRoot, workspaceId)
  const operationDirectory = path.join(root, 'runs', `naming_${operationId}`)
  const sourceSnapshot = path.join(operationDirectory, '.source.pdb')
  const output = path.join(operationDirectory, outputName(request, sourceArtifact.file))
  const reportFile = path.join(operationDirectory, 'report.json')
  let retainedStdout: string | undefined
  let retainedStderr: string | undefined
  let retainedReport: Buffer | undefined
  try {
    pruneNamingFailures(root, settings.failureRetention)
    fs.mkdirSync(operationDirectory, { recursive: false, mode: 0o700 })
    writePrivateFile(sourceSnapshot, sourceBytes)
    const args = [
      sourceSnapshot, '-o', output,
      '--target-ff', request.target.forceField,
      '--profile', request.target.profile,
      '--report-json', reportFile,
    ]
    if (request.variantOverrides?.length) {
      const overridesFile = path.join(operationDirectory, 'variant-overrides.json')
      writeJsonAtomic(overridesFile, request.variantOverrides)
      fs.chmodSync(overridesFile, 0o600)
      args.push('--variant-overrides', overridesFile)
    }
    if (request.dryRun) args.push('--dry-run')

    const run = await runner('atom-names', args, operationDirectory, {
      timeoutMs: settings.timeoutMs, maxOutputBytes: MAX_OUTPUT_BYTES, killGraceMs: 2_000, signal,
    })
    retainedStdout = run.stdout
    retainedStderr = run.stderr
    writePrivateFile(path.join(operationDirectory, 'stdout.log'), run.stdout)
    writePrivateFile(path.join(operationDirectory, 'stderr.log'), run.stderr)
    if (run.failure && run.failure !== 'nonzero-exit') {
      const failures = {
        overloaded: [503, 'SERVER_BUSY', 'DVBFixer process queue is full'],
        shutdown: [503, 'SERVER_SHUTTING_DOWN', 'DVBFixer server is shutting down'],
        timeout: [504, 'NAMING_TIMEOUT', 'atom-names timed out'],
        cancelled: [499, 'REQUEST_CANCELLED', 'naming conversion was cancelled'],
        'spawn-error': [500, 'SUBPROCESS_FAILED', 'atom-names could not be started'],
      } as const
      const [statusCode, code, message] = failures[run.failure]
      throw new NamingApiError(statusCode, code, message)
    }
    const parsed = parseReport(reportFile, settings.maxReportBytes)
    fs.chmodSync(reportFile, 0o600)
    retainedReport = parsed.bytes
    validateReportRequest(parsed.report, request)
    if (run.code !== 0 || parsed.report.status !== 'success' || !parsed.report.result) {
      const cliError = parsed.report.error
      const isConversionError = cliError?.category === 'conversion'
      throw new NamingApiError(
        isConversionError ? 422 : 500,
        isConversionError ? cliError.code : 'SUBPROCESS_FAILED',
        isConversionError ? cliError.message : 'atom-names failed',
        isConversionError ? cliError.details : undefined,
      )
    }
    const report = parsed.report
    const conversionResult = report.result
    if (!conversionResult) {
      throw new NamingApiError(500, 'INVALID_CLI_REPORT', 'successful atom-names report has no result')
    }
    if (report.output.path !== output) {
      throw new NamingApiError(500, 'CLI_REPORT_MISMATCH', 'atom-names reported an unexpected output path')
    }

    let outputArtifact: WorkspaceArtifact | null = null
    let relativeOutput: string | null = null
    let outputStat: fs.Stats | null = null
    try { outputStat = fs.lstatSync(output) } catch { /* missing */ }
    if (outputStat?.isSymbolicLink()) {
      // Unlink the directory entry itself, including a dangling symlink.
      // Some Node versions treat rmSync(force) as a no-op for dangling links.
      try { fs.unlinkSync(output) } catch { /* failure handling will quarantine the run */ }
      throw new NamingApiError(500, 'UNSAFE_OUTPUT', 'atom-names output is not a private regular file')
    }
    if (request.dryRun) {
      if (report.output.written || outputStat) {
        throw new NamingApiError(500, 'CLI_REPORT_MISMATCH', 'dry run unexpectedly published an output')
      }
    } else {
      if (!report.output.written || !outputStat?.isFile()) {
        throw new NamingApiError(500, 'MISSING_OUTPUT', 'atom-names did not publish the expected output')
      }
      let outputBytes: Buffer | null
      try { outputBytes = readBoundedRegularFile(output, settings.maxSourceBytes) } catch {
        try { fs.unlinkSync(output) } catch { /* failure handling will quarantine the run */ }
        throw new NamingApiError(500, 'UNSAFE_OUTPUT', 'atom-names output is not a private regular file')
      }
      if (!outputBytes) {
        throw new NamingApiError(500, 'OUTPUT_TOO_LARGE', 'atom-names output exceeds the configured source limit')
      }
      if (!outputBytes.length || report.output.bytes !== outputBytes.length || report.output.sha256 !== sha256(outputBytes)) {
        throw new NamingApiError(500, 'OUTPUT_DIGEST_MISMATCH', 'atom-names output does not match its report')
      }
      replaceWithPrivateFile(output, outputBytes)
      const relativeFolder = path.relative(root, operationDirectory).replace(/\\/g, '/')
      relativeOutput = path.relative(root, output).replace(/\\/g, '/')
      const provenance: NamingConversionProvenance = {
        operation: 'pdb-force-field-naming', operationId, apiVersion: 1,
        reportSchemaVersion: 1, sourceArtifactId: sourceArtifact.id,
        sourceFile: sourceArtifact.file, sourceSha256, command: 'atom-names',
        targetForceField: request.target.forceField, profile: request.target.profile,
        variantOverrides: request.variantOverrides || [], reportSha256: sha256(parsed.bytes),
        outputSha256: report.output.sha256, dvbfixerVersion: report.tool.version, serviceVersion,
      }
      outputArtifact = {
        id: crypto.randomUUID(), file: relativeOutput, name: path.basename(output),
        kind: 'structure', folder: relativeFolder, parent: sourceArtifact.file,
        command: 'atom-names', artifactType: 'naming-conversion', namingProvenance: provenance,
      }
    }

    const response: NamingConversionResponse = {
      operationId, status: 'succeeded', sourceArtifactId: sourceArtifact.id,
      outputArtifact: outputArtifact && {
        id: outputArtifact.id, file: outputArtifact.file, name: outputArtifact.name, kind: 'structure',
      },
      output: { bytes: report.output.bytes!, sha256: report.output.sha256! },
      result: conversionResult,
    }
    if (!Value.Check(NamingConversionResponseSchema, response)) {
      throw new NamingApiError(500, 'INVALID_RESPONSE', schemaError(NamingConversionResponseSchema, response))
    }
    if (outputArtifact && relativeOutput) {
      removeSuccessHelpers(operationDirectory, output)
      updateWorkspace(dataRoot, workspaceId, latest => {
        authorizePublication?.(latest)
        const currentSource = latest.artifacts.find(artifact => artifact.id === sourceArtifact.id)
        let currentSourceBytes: Buffer | null = null
        try { currentSourceBytes = readBoundedRegularFile(source, settings.maxSourceBytes) } catch { /* changed */ }
        if (!currentSource || currentSource.hidden || currentSource.kind !== 'structure' ||
            currentSource.file !== sourceArtifact.file || !currentSourceBytes ||
            sha256(currentSourceBytes) !== sourceSha256) {
          throw new NamingApiError(409, 'SOURCE_ARTIFACT_CHANGED', 'input artifact changed during conversion')
        }
        if (latest.artifacts.some(artifact => artifact.file === relativeOutput)) {
          throw new NamingApiError(409, 'OUTPUT_CONFLICT', 'output artifact path already exists')
        }
        latest.artifacts.push(outputArtifact!)
        return latest
      })
    }
    if (request.dryRun) fs.rmSync(operationDirectory, { recursive: true, force: true })
    return { statusCode: request.dryRun ? 200 : 201, response }
  } catch (error) {
    // A failed child or malformed report can bypass output validation above.
    // Never retain a child-created output symlink in the diagnostic archive.
    try {
      if (fs.lstatSync(output).isSymbolicLink()) fs.unlinkSync(output)
    } catch { /* missing output or cleanup failure must not replace the original error */ }
    if (error instanceof WorkspaceQuotaExceededError) {
      try { fs.rmSync(operationDirectory, { recursive: true, force: true }) } catch { /* preserve the quota failure */ }
    } else {
      try { fs.rmSync(sourceSnapshot, { force: true }) } catch { /* preserve the original failure */ }
      try {
        if (fs.existsSync(operationDirectory)) {
          if (retainedStdout !== undefined) writePrivateFile(path.join(operationDirectory, 'stdout.log'), retainedStdout)
          if (retainedStderr !== undefined) writePrivateFile(path.join(operationDirectory, 'stderr.log'), retainedStderr)
          if (retainedReport) writePrivateFile(reportFile, retainedReport)
          if (request.variantOverrides?.length) {
            const overridesFile = path.join(operationDirectory, 'variant-overrides.json')
            if (!fs.existsSync(overridesFile)) {
              writeJsonAtomic(overridesFile, request.variantOverrides)
              fs.chmodSync(overridesFile, 0o600)
            }
          }
        }
      } catch { /* quarantine is still attempted if diagnostic restoration fails */ }
      let retainFailure = true
      try { assertWorkspaceQuota(root) } catch (quotaError) {
        if (quotaError instanceof WorkspaceQuotaExceededError) {
          try { fs.rmSync(operationDirectory, { recursive: true, force: true }) } catch { /* preserve the original failure */ }
          retainFailure = false
        }
      }
      if (retainFailure) {
        try {
          moveToFailureArea(operationDirectory, root)
          pruneNamingFailures(root, settings.failureRetention)
        } catch { /* preserve the original failure */ }
      }
    }
    throw error
  } finally {
    release()
  }
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(body))
}

function sendError(res: ServerResponse, error: unknown, requestId: string): void {
  const apiError = error instanceof NamingApiError ? error : null
  const status = apiError?.statusCode || errorStatus(error)
  const body = {
    error: {
      code: apiError?.code || (status === 413 ? 'PAYLOAD_TOO_LARGE'
        : status === 507 ? 'WORKSPACE_QUOTA_EXCEEDED' : 'INTERNAL_ERROR'),
      message: apiError?.message || 'unexpected server error',
      ...(apiError?.details === undefined ? {} : { details: apiError.details }),
      requestId,
    },
  }
  if (!Value.Check(ApiErrorSchema, body)) {
    return sendJson(res, 500, { error: { code: 'INTERNAL_ERROR', message: 'invalid error response', requestId } })
  }
  sendJson(res, status, body)
}

export function registerNamingApi(
  server: ApiRouteHost,
  dataRoot: string,
  runner: NamingRunner = runDvbfixerArgs,
  principalSource: (request: IncomingMessage) => string = () => 'local',
  legacyOwnerPrincipalId = 'local',
  serviceVersion = 'unknown',
): void {
  server.middlewares.use('/api/v1', async (req: IncomingMessage, res: ServerResponse, next: () => void) => {
    const route = (req.url || '').split('?')[0]
    if (req.method === 'GET' && route === '/openapi.json') {
      return sendJson(res, 200, NAMING_OPENAPI_DOCUMENT)
    }
    const match = route.match(/^\/workspaces\/([^/]+)\/naming-conversions$/)
    if (!match) return next()
    const requestId = ensureRequestId(req, res)
    if (req.method !== 'POST') return sendError(res, new NamingApiError(405, 'METHOD_NOT_ALLOWED', 'method not allowed'), requestId)
    if (!String(req.headers['content-type'] || '').toLowerCase().startsWith('application/json')) {
      return sendError(res, new NamingApiError(415, 'UNSUPPORTED_MEDIA_TYPE', 'Content-Type must be application/json'), requestId)
    }
    try {
      let workspaceId: string
      try { workspaceId = decodeURIComponent(match[1]) } catch {
        throw new NamingApiError(400, 'INVALID_WORKSPACE_ID', 'workspace ID is not valid URL encoding')
      }
      if (!/^[a-zA-Z0-9_-]+$/.test(workspaceId)) {
        throw new NamingApiError(400, 'INVALID_WORKSPACE_ID', 'workspace ID contains unsupported characters')
      }
      let value: unknown
      try { value = JSON.parse((await readRequestBody(req)).toString('utf8')) } catch (error) {
        if (errorStatus(error) === 413) throw error
        throw new NamingApiError(400, 'INVALID_JSON', 'request body is not valid JSON')
      }
      const request = parseRequest(value)
      const principalId = principalSource(req)
      const authorize = () => {
        try {
          const workspace = loadWorkspace(dataRoot, workspaceId, legacyOwnerPrincipalId)
          assertWorkspaceAccess(workspace, principalId, 'writer')
          assertWorkspaceQuota(workspaceRoot(dataRoot, workspaceId))
          return workspace
        } catch (error) {
          if (error instanceof WorkspaceQuotaExceededError) throw error
          const status = errorStatus(error, 404)
          throw new NamingApiError(
            status === 403 ? 403 : 404,
            status === 403 ? 'WORKSPACE_ACCESS_DENIED' : 'WORKSPACE_NOT_FOUND',
            status === 403 ? 'workspace write access is required' : 'workspace does not exist',
          )
        }
      }
      authorize()
      const controller = new AbortController()
      const abortOnClose = () => { if (!res.writableFinished) controller.abort() }
      if (typeof res.once === 'function') res.once('close', abortOnClose)
      const result = await executeNamingConversion(
        dataRoot,
        workspaceId,
        request,
        runner,
        () => { authorize() },
        controller.signal,
        serviceVersion,
      )
      if (typeof res.removeListener === 'function') res.removeListener('close', abortOnClose)
      return sendJson(res, result.statusCode, result.response)
    } catch (error) {
      return sendError(res, error, requestId)
    }
  })
}
