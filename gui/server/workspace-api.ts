import type { IncomingMessage, ServerResponse } from 'node:http'
import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'
import { Readable } from 'node:stream'
import zlib from 'node:zlib'
import { errorStatus, readRequestBody } from './request-body'
import type { ApiRouteHost } from './http-types'
import {
  assertWorkspaceQuota, storageQuotaSettings, WorkspaceQuotaExceededError,
} from './storage-quota'
import { withGlobalMigrationLock, withWorkspaceManifestLock } from './workspace-lock'

export interface WorkspaceArtifact {
  id: string
  file: string
  name: string
  kind: 'structure' | 'artifact'
  folder?: string
  parent?: string
  command?: string
  artifactType?: string
  /** Internal run bookkeeping retained on disk but hidden from user pickers. */
  hidden?: boolean
  /** Original legacy-library path retained only to make metadata migration exact. */
  legacySourceFile?: string
  organism?: string
  method?: string
  resolution?: string
  description?: string
  iggSubtype?: string
  allotype?: string
  equivalentChains?: string[][]
  /** Opaque identifiers retained only for read-only compatibility with retired Antibody Engineer artifacts. */
  mutationIds?: number[]
  /** Immutable resolved-mutation provenance retained from retired Antibody Engineer artifacts. */
  mutationsResolved?: string
  /** Historical Antibody Engineer provenance; no active workflow consumes these fields. */
  engineerChecksum?: string
  hasGlycan?: boolean
  scheme?: 'EU' | 'Kabat'
  namingProvenance?: NamingConversionProvenance
  workflowProvenance?: WorkflowProvenance
}

export interface WorkflowProvenance {
  apiVersion: 1
  command: string
  serviceVersion: string
  dvbfixerVersion: string
  request: {
    inputs: Record<string, string | string[]>
    values: Record<string, unknown>
    fastaSha256: string | null
  }
  resolvedInputs: Array<{ artifactId: string | null; file: string; sha256: string }>
  outputs: Array<{ artifactId: string; file: string; sha256: string }>
}

export interface NamingConversionProvenance {
  operation: 'pdb-force-field-naming'
  operationId: string
  apiVersion: 1
  reportSchemaVersion: 1
  sourceArtifactId: string
  sourceFile: string
  sourceSha256: string
  command: 'atom-names'
  targetForceField: 'amber' | 'amber19sb' | 'charmm'
  profile: 'gromacs' | 'standard'
  variantOverrides: Array<{
    chainId: string
    residueNumber: string
    insertionCode: string
    variant: string
  }>
  reportSha256: string
  outputSha256: string
  dvbfixerVersion: string
  /** Optional only for manifests created before service-version provenance shipped. */
  serviceVersion?: string
}

export interface WorkspaceArtifactMetadataPatch {
  revision: number
  name?: string
  organism?: string | null
  method?: string | null
  resolution?: string | number | null
  description?: string | null
  iggSubtype?: string | null
  allotype?: string | null
  equivalentChains?: string[][] | null
}

export interface WorkspaceManifest {
  /** Version 1 is accepted only as an ownerless legacy input and is migrated on load/save. */
  version: 1 | 2
  /** Monotonically increasing optimistic-concurrency token. */
  revision: number
  id: string
  name: string
  createdAt: string
  updatedAt: string
  primaryFile: string | null
  secondaryFile: string | null
  artifacts: WorkspaceArtifact[]
  toolState: Record<string, unknown>
  ownerPrincipalId?: string
  acl?: WorkspaceAclEntry[]
  provisionalOwner?: boolean
}

export type WorkspaceAclRole = 'reader' | 'writer'
export type WorkspaceRole = WorkspaceAclRole | 'owner'
export type WorkspaceAccess = WorkspaceRole

export interface WorkspaceAclEntry {
  principalId: string
  role: WorkspaceAclRole
}

export interface WorkspaceManifestV2 extends WorkspaceManifest {
  version: 2
  ownerPrincipalId: string
  acl: WorkspaceAclEntry[]
}

export interface WorkspaceAclPatch {
  revision: number
  acl: WorkspaceAclEntry[]
}

/** Identity used by the local, non-authenticated GUI until an auth adapter supplies one. */
export const LOCAL_WORKSPACE_PRINCIPAL_ID = 'local'

export interface WorkspacePatch {
  revision: number
  toolState?: Record<string, unknown>
  primaryFile?: string | null
  secondaryFile?: string | null
  artifactOrder?: string[]
}

export class WorkspaceRevisionConflictError extends Error {
  readonly statusCode = 409
  readonly expectedRevision: number
  readonly receivedRevision: unknown

  constructor(expectedRevision: number, receivedRevision: unknown) {
    super(`workspace revision conflict: current revision is ${expectedRevision}, received ${String(receivedRevision)}`)
    this.name = 'WorkspaceRevisionConflictError'
    this.expectedRevision = expectedRevision
    this.receivedRevision = receivedRevision
  }
}

export class WorkspaceAuthorizationError extends Error {
  readonly statusCode: 403 | 404

  constructor(statusCode: 403 | 404, message: string) {
    super(message)
    this.name = 'WorkspaceAuthorizationError'
    this.statusCode = statusCode
  }
}

class WorkspaceArtifactMutationError extends Error {
  readonly statusCode = 400
}

const ALLOWED = new Set([
  '.pdb', '.cif', '.mmcif', '.gro', '.fasta', '.fa', '.faa', '.pir', '.aln',
  '.xtc', '.trr', '.dcd', '.tpr', '.mol2', '.sdf', '.top', '.itp', '.dat',
  '.json', '.txt', '.html', '.csv', '.log', '.md', '.yaml', '.yml', '.toml',
  '.xml', '.pml', '.py', '.sh', '.mdp',
])

const CONTENT_TYPES: Record<string, string> = {
  '.pdb': 'chemical/x-pdb', '.cif': 'chemical/x-cif', '.mmcif': 'chemical/x-cif',
  '.gro': 'chemical/x-gromacs-gro', '.mol2': 'chemical/x-mol2', '.sdf': 'chemical/x-mdl-sdfile',
  '.fasta': 'text/x-fasta', '.fa': 'text/x-fasta', '.faa': 'text/x-fasta',
  '.pir': 'text/plain', '.aln': 'text/plain', '.top': 'text/plain', '.itp': 'text/plain',
  '.dat': 'text/plain', '.txt': 'text/plain', '.log': 'text/plain', '.csv': 'text/csv',
  '.json': 'application/json', '.html': 'text/html', '.xml': 'application/xml',
  '.yaml': 'application/yaml', '.yml': 'application/yaml', '.toml': 'application/toml',
  '.xtc': 'application/octet-stream', '.trr': 'application/octet-stream',
  '.dcd': 'application/octet-stream', '.tpr': 'application/octet-stream',
}

const PROTECTED_ARTIFACT_BASENAMES = new Set(['workspace.json', 'homology-project.json'])

export function isProtectedArtifactPath(file: string): boolean {
  return PROTECTED_ARTIFACT_BASENAMES.has(path.basename(file).toLowerCase())
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(body))
}

export function workspaceOrderPath(dataRoot: string, principalId = LOCAL_WORKSPACE_PRINCIPAL_ID): string {
  if (principalId === LOCAL_WORKSPACE_PRINCIPAL_ID) return path.join(dataRoot, '.workspace-order.json')
  const key = crypto.createHash('sha256').update(principalId).digest('hex').slice(0, 16)
  return path.join(dataRoot, `.workspace-order-${key}.json`)
}

function readWorkspaceOrder(dataRoot: string, principalId = LOCAL_WORKSPACE_PRINCIPAL_ID): string[] {
  try {
    const value = JSON.parse(fs.readFileSync(workspaceOrderPath(dataRoot, principalId), 'utf8'))
    return Array.isArray(value) ? value.filter(item => typeof item === 'string') : []
  } catch { return [] }
}

function writeWorkspaceOrder(dataRoot: string, ids: string[], principalId = LOCAL_WORKSPACE_PRINCIPAL_ID): void {
  writeJsonAtomic(workspaceOrderPath(dataRoot, principalId), ids)
}

export function writeJsonAtomic(file: string, value: unknown): void {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const temporary = path.join(
    path.dirname(file),
    `.${path.basename(file)}.${process.pid}.${crypto.randomUUID()}.tmp`,
  )
  let descriptor: number | undefined
  try {
    descriptor = fs.openSync(temporary, 'wx', 0o600)
    fs.writeFileSync(descriptor, `${JSON.stringify(value, null, 2)}\n`, 'utf8')
    fs.fsyncSync(descriptor)
    fs.closeSync(descriptor)
    descriptor = undefined
    fs.renameSync(temporary, file)
  } catch (error) {
    if (descriptor !== undefined) fs.closeSync(descriptor)
    try { fs.unlinkSync(temporary) } catch { /* best-effort cleanup */ }
    throw error
  }
}

function jsonByteLength(value: unknown): number {
  return Buffer.byteLength(`${JSON.stringify(value, null, 2)}\n`)
}

function writeBufferAtomic(file: string, content: Buffer): void {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const temporary = path.join(
    path.dirname(file),
    `.${path.basename(file)}.${process.pid}.${crypto.randomUUID()}.tmp`,
  )
  let descriptor: number | undefined
  try {
    descriptor = fs.openSync(temporary, 'wx', 0o600)
    fs.writeFileSync(descriptor, content)
    fs.fsyncSync(descriptor)
    fs.closeSync(descriptor)
    descriptor = undefined
    fs.renameSync(temporary, file)
  } catch (error) {
    if (descriptor !== undefined) fs.closeSync(descriptor)
    try { fs.unlinkSync(temporary) } catch { /* best-effort cleanup */ }
    throw error
  }
}

function tarOctal(value: number, width: number): Buffer {
  return Buffer.from(`${value.toString(8).padStart(width - 1, '0')}\0`, 'ascii')
}

function splitTarPath(name: string): { name: string; prefix: string } {
  if (Buffer.byteLength(name) <= 100) return { name, prefix: '' }
  const separators = [...name.matchAll(/\//g)].map(match => match.index!)
  for (const separator of separators.reverse()) {
    const prefix = name.slice(0, separator)
    const basename = name.slice(separator + 1)
    if (Buffer.byteLength(prefix) <= 155 && Buffer.byteLength(basename) <= 100) {
      return { name: basename, prefix }
    }
  }
  throw new Error(`artifact path is too long for TAR archive: ${name}`)
}

function tarHeader(name: string, size: number, mtime: number): Buffer {
  const header = Buffer.alloc(512)
  const tarPath = splitTarPath(name)
  Buffer.from(tarPath.name).copy(header, 0)
  Buffer.from(tarPath.prefix).copy(header, 345)
  tarOctal(0o644, 8).copy(header, 100)
  tarOctal(0, 8).copy(header, 108)
  tarOctal(0, 8).copy(header, 116)
  tarOctal(size, 12).copy(header, 124)
  tarOctal(Math.floor(mtime / 1000), 12).copy(header, 136)
  header.fill(0x20, 148, 156)
  header[156] = '0'.charCodeAt(0)
  Buffer.from('ustar\0').copy(header, 257)
  Buffer.from('00').copy(header, 263)
  tarOctal([...header].reduce((sum, byte) => sum + byte, 0), 8).copy(header, 148)
  return header
}

async function* workspaceArchive(dataRoot: string, workspace: WorkspaceManifest): AsyncGenerator<Buffer> {
  for (const artifact of workspace.artifacts.filter(artifact => !artifact.hidden && !isProtectedArtifactPath(artifact.file))) {
    const file = resolveWorkspaceFile(dataRoot, workspace.id, artifact.file)
    const stat = fs.statSync(file)
    if (!stat.isFile()) continue
    yield tarHeader(artifact.file, stat.size, stat.mtimeMs)
    for await (const chunk of fs.createReadStream(file)) yield Buffer.from(chunk)
    const padding = (512 - stat.size % 512) % 512
    if (padding) yield Buffer.alloc(padding)
  }
  yield Buffer.alloc(1024)
}

function safeId(id: string): string {
  if (!/^[a-zA-Z0-9_-]+$/.test(id)) throw new Error('invalid workspace id')
  return id
}

function existingRealPathInside(root: string, candidate: string): string | null {
  if (!fs.existsSync(root) || !fs.existsSync(candidate)) return null
  const realRoot = fs.realpathSync(root)
  const realCandidate = fs.realpathSync(candidate)
  const relative = path.relative(realRoot, realCandidate)
  return relative.startsWith('..') || path.isAbsolute(relative) ? null : realCandidate
}

export function workspacesRoot(dataRoot: string): string {
  const root = path.join(dataRoot, 'projects')
  fs.mkdirSync(root, { recursive: true })
  return root
}

export function workspaceRoot(dataRoot: string, id: string): string {
  return path.join(workspacesRoot(dataRoot), safeId(id))
}

function manifestPath(dataRoot: string, id: string): string {
  return path.join(workspaceRoot(dataRoot, id), 'workspace.json')
}

function workspaceDeletionMarker(dataRoot: string, id: string): string {
  return path.join(dataRoot, '.workspace-deletions', `${safeId(id)}.json`)
}

function completePendingWorkspaceDeletionUnlocked(dataRoot: string, id: string): boolean {
  const marker = workspaceDeletionMarker(dataRoot, id)
  if (!fs.existsSync(marker)) return false
  const record = JSON.parse(fs.readFileSync(marker, 'utf8')) as { workspaceId?: unknown; trashName?: unknown }
  if (record.workspaceId !== id || typeof record.trashName !== 'string' ||
      safeId(record.trashName) !== record.trashName || !record.trashName.startsWith(`${safeId(id)}-`)) {
    throw new Error(`invalid workspace deletion marker: ${id}`)
  }
  const source = workspaceRoot(dataRoot, id)
  if (!fs.existsSync(source)) return true
  const trash = path.join(dataRoot, '_workspace_trash')
  const destination = path.join(trash, record.trashName)
  fs.mkdirSync(trash, { recursive: true })
  const target = fs.existsSync(destination)
    ? path.join(trash, `${record.trashName}-late-${crypto.randomUUID()}`)
    : destination
  fs.renameSync(source, target)
  return true
}

function reconcilePendingWorkspaceDeletions(dataRoot: string): void {
  const markerRoot = path.join(dataRoot, '.workspace-deletions')
  if (!fs.existsSync(markerRoot)) return
  for (const entry of fs.readdirSync(markerRoot, { withFileTypes: true })) {
    if (!entry.isFile() || !entry.name.endsWith('.json')) continue
    const id = entry.name.slice(0, -'.json'.length)
    withWorkspaceManifestLock(dataRoot, id, () => completePendingWorkspaceDeletionUnlocked(dataRoot, id))
  }
}

function validPrincipalId(value: unknown): value is string {
  return typeof value === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/.test(value)
}

function validateAcl(ownerPrincipalId: unknown, value: unknown): asserts value is WorkspaceAclEntry[] {
  if (!validPrincipalId(ownerPrincipalId)) throw new Error('invalid workspace ownerPrincipalId')
  if (!Array.isArray(value)) throw new Error('invalid workspace acl')
  const seen = new Set<string>()
  for (const candidate of value) {
    if (!candidate || typeof candidate !== 'object' || Array.isArray(candidate)) {
      throw new Error('invalid workspace acl entry')
    }
    const entry = candidate as Record<string, unknown>
    if (Object.keys(entry).some(key => key !== 'principalId' && key !== 'role') ||
        !validPrincipalId(entry.principalId) ||
        (entry.role !== 'reader' && entry.role !== 'writer')) {
      throw new Error('invalid workspace acl entry')
    }
    if (entry.principalId === ownerPrincipalId) throw new Error('workspace owner must not appear in acl')
    if (seen.has(entry.principalId)) throw new Error(`duplicate workspace acl principal: ${entry.principalId}`)
    seen.add(entry.principalId)
  }
}

function manifestV2(
  manifest: WorkspaceManifest,
  legacyOwnerPrincipalId: string,
  provisionalOwner = false,
): WorkspaceManifestV2 {
  if (manifest.version === 1) {
    if (manifest.ownerPrincipalId !== undefined || manifest.acl !== undefined ||
        manifest.provisionalOwner !== undefined) {
      throw new Error('version 1 workspace must not contain security fields')
    }
    if (!validPrincipalId(legacyOwnerPrincipalId)) throw new Error('invalid legacy workspace ownerPrincipalId')
    return {
      ...manifest,
      version: 2,
      ownerPrincipalId: legacyOwnerPrincipalId,
      acl: [],
      ...(provisionalOwner ? { provisionalOwner: true } : {}),
    }
  }
  if (manifest.version !== 2) throw new Error(`unsupported workspace manifest version: ${String(manifest.version)}`)
  validateAcl(manifest.ownerPrincipalId, manifest.acl)
  if (manifest.provisionalOwner !== undefined && manifest.provisionalOwner !== true) {
    throw new Error('invalid workspace provisionalOwner')
  }
  if (manifest.provisionalOwner === true &&
      (manifest.ownerPrincipalId !== LOCAL_WORKSPACE_PRINCIPAL_ID || manifest.acl.length > 0)) {
    throw new Error('provisional workspace owner must be local with an empty acl')
  }
  return manifest as WorkspaceManifestV2
}

export function workspaceRole(workspace: WorkspaceManifestV2, principalId: string): WorkspaceRole | null {
  if (workspace.ownerPrincipalId === principalId) return 'owner'
  return workspace.acl.find(entry => entry.principalId === principalId)?.role || null
}

function workspaceView(workspace: WorkspaceManifestV2, principalId: string): WorkspaceManifestV2 & { effectiveRole: WorkspaceRole } {
  return { ...workspace, effectiveRole: assertWorkspaceAccess(workspace, principalId) }
}

export function canReadWorkspace(workspace: WorkspaceManifestV2, principalId: string): boolean {
  return workspaceRole(workspace, principalId) !== null
}

export function canWriteWorkspace(workspace: WorkspaceManifestV2, principalId: string): boolean {
  const role = workspaceRole(workspace, principalId)
  return role === 'owner' || role === 'writer'
}

export function isWorkspaceOwner(workspace: WorkspaceManifestV2, principalId: string): boolean {
  return workspaceRole(workspace, principalId) === 'owner'
}

export function assertWorkspaceAccess(
  workspace: WorkspaceManifestV2,
  principalId: string,
  required: WorkspaceAccess = 'reader',
): WorkspaceRole {
  const role = validPrincipalId(principalId) ? workspaceRole(workspace, principalId) : null
  if (role === null) throw new WorkspaceAuthorizationError(404, `workspace not found: ${workspace.id}`)
  if (required === 'owner' && role !== 'owner') {
    throw new WorkspaceAuthorizationError(403, 'workspace owner access required')
  }
  if (required === 'writer' && role === 'reader') {
    throw new WorkspaceAuthorizationError(403, 'workspace writer access required')
  }
  return role
}

function readWorkspace(
  dataRoot: string,
  id: string,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
): { workspace: WorkspaceManifestV2; wasLegacy: boolean } {
  if (fs.existsSync(workspaceDeletionMarker(dataRoot, id))) throw new Error(`workspace not found: ${id}`)
  const file = manifestPath(dataRoot, id)
  if (!fs.existsSync(file)) throw new Error(`workspace not found: ${id}`)
  const parsed = JSON.parse(fs.readFileSync(file, 'utf8')) as WorkspaceManifest
  const wasLegacy = parsed.version === 1
  const workspace = manifestV2(parsed, legacyOwnerPrincipalId)
  workspace.revision = Number.isSafeInteger(workspace.revision) && workspace.revision >= 0
    ? workspace.revision : 0
  workspace.artifacts = Array.isArray(workspace.artifacts)
    ? workspace.artifacts.filter((artifact): artifact is WorkspaceArtifact =>
      !!artifact && typeof artifact === 'object' && typeof artifact.file === 'string' &&
      !isProtectedArtifactPath(artifact.file))
    : []
  for (const artifact of workspace.artifacts) sanitizeArtifactMetadata(artifact)
  workspace.toolState = workspace.toolState && typeof workspace.toolState === 'object' ? workspace.toolState : {}
  return { workspace, wasLegacy }
}

export function loadWorkspace(
  dataRoot: string,
  id: string,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
): WorkspaceManifestV2 {
  const loaded = readWorkspace(dataRoot, id, legacyOwnerPrincipalId)
  if (!loaded.wasLegacy) return loaded.workspace
  return withWorkspaceManifestLock(dataRoot, id, () => {
    const current = readWorkspace(dataRoot, id, legacyOwnerPrincipalId)
    if (current.wasLegacy) writeJsonAtomic(manifestPath(dataRoot, id), current.workspace)
    return current.workspace
  })
}

export function migrateWorkspaceOwnership(
  dataRoot: string,
  legacyOwnerPrincipalId: string,
  authenticationEnabled = false,
): void {
  const root = workspacesRoot(dataRoot)
  for (const entry of fs.readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue
    const file = manifestPath(dataRoot, entry.name)
    if (!fs.existsSync(file)) continue
    withWorkspaceManifestLock(dataRoot, entry.name, () => {
      const parsed = JSON.parse(fs.readFileSync(file, 'utf8')) as WorkspaceManifest
      if (parsed.version === 1) {
        writeJsonAtomic(file, manifestV2(
          parsed,
          legacyOwnerPrincipalId,
          !authenticationEnabled && legacyOwnerPrincipalId === LOCAL_WORKSPACE_PRINCIPAL_ID,
        ))
        return
      }
      const secured = manifestV2(parsed, legacyOwnerPrincipalId)
      if (authenticationEnabled && secured.provisionalOwner === true) {
        const { provisionalOwner: _provisionalOwner, ...withoutMarker } = secured
        void _provisionalOwner
        const migrated = {
          ...withoutMarker,
          ownerPrincipalId: legacyOwnerPrincipalId,
          acl: secured.acl.filter(entry => entry.principalId !== legacyOwnerPrincipalId),
        }
        validateAcl(migrated.ownerPrincipalId, migrated.acl)
        writeJsonAtomic(file, migrated)
      }
    })
  }
}

const STRING_METADATA_FIELDS = [
  'organism', 'method', 'resolution', 'description', 'iggSubtype', 'allotype',
] as const

function validEquivalentChains(value: unknown): value is string[][] {
  return Array.isArray(value) && value.every(group =>
    Array.isArray(group) && group.every(chain => typeof chain === 'string'))
}

function sanitizeArtifactMetadata(artifact: WorkspaceArtifact): void {
  for (const field of STRING_METADATA_FIELDS) {
    if (artifact[field] !== undefined && typeof artifact[field] !== 'string') delete artifact[field]
  }
  if (artifact.equivalentChains !== undefined && !validEquivalentChains(artifact.equivalentChains)) {
    delete artifact.equivalentChains
  }
  if (artifact.legacySourceFile !== undefined && typeof artifact.legacySourceFile !== 'string') delete artifact.legacySourceFile
  if (artifact.mutationIds !== undefined && (!Array.isArray(artifact.mutationIds) || artifact.mutationIds.some(id => !Number.isInteger(id)))) delete artifact.mutationIds
  if (artifact.mutationsResolved !== undefined && typeof artifact.mutationsResolved !== 'string') delete artifact.mutationsResolved
  if (artifact.engineerChecksum !== undefined && typeof artifact.engineerChecksum !== 'string') delete artifact.engineerChecksum
  if (artifact.hasGlycan !== undefined && typeof artifact.hasGlycan !== 'boolean') delete artifact.hasGlycan
  if (artifact.scheme !== undefined && artifact.scheme !== 'EU' && artifact.scheme !== 'Kabat') delete artifact.scheme
  if (artifact.namingProvenance !== undefined && !validNamingProvenance(artifact.namingProvenance)) delete artifact.namingProvenance
  if (artifact.workflowProvenance !== undefined && !validWorkflowProvenance(artifact.workflowProvenance)) delete artifact.workflowProvenance
}

function validWorkflowProvenance(value: unknown): value is WorkflowProvenance {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  if (item.apiVersion !== 1 || typeof item.command !== 'string' ||
      typeof item.serviceVersion !== 'string' || typeof item.dvbfixerVersion !== 'string' ||
      !item.request || typeof item.request !== 'object' || !Array.isArray(item.resolvedInputs) ||
      !Array.isArray(item.outputs)) return false
  const request = item.request as Record<string, unknown>
  if (!request.inputs || typeof request.inputs !== 'object' || !request.values ||
      typeof request.values !== 'object' ||
      (request.fastaSha256 !== null && typeof request.fastaSha256 !== 'string')) return false
  const validDigest = (entry: unknown, output: boolean): boolean => {
    if (!entry || typeof entry !== 'object') return false
    const field = entry as Record<string, unknown>
    return typeof field.file === 'string' && /^[a-f0-9]{64}$/.test(String(field.sha256)) &&
      (output ? typeof field.artifactId === 'string'
        : field.artifactId === null || typeof field.artifactId === 'string')
  }
  return item.resolvedInputs.every(entry => validDigest(entry, false)) &&
    item.outputs.every(entry => validDigest(entry, true))
}

function validNamingProvenance(value: unknown): value is NamingConversionProvenance {
  if (!value || typeof value !== 'object') return false
  const item = value as Record<string, unknown>
  return item.operation === 'pdb-force-field-naming' && item.command === 'atom-names' &&
    item.apiVersion === 1 && item.reportSchemaVersion === 1 &&
    typeof item.operationId === 'string' && typeof item.sourceArtifactId === 'string' &&
    typeof item.sourceFile === 'string' && typeof item.sourceSha256 === 'string' &&
    (item.targetForceField === 'amber' || item.targetForceField === 'amber19sb' ||
      item.targetForceField === 'charmm') &&
    (item.profile === 'gromacs' || item.profile === 'standard') && Array.isArray(item.variantOverrides) &&
    item.variantOverrides.every(override => {
      if (!override || typeof override !== 'object') return false
      const entry = override as Record<string, unknown>
      return typeof entry.chainId === 'string' && typeof entry.residueNumber === 'string' &&
        typeof entry.insertionCode === 'string' && typeof entry.variant === 'string'
    }) &&
    typeof item.reportSha256 === 'string' && typeof item.outputSha256 === 'string' &&
    typeof item.dvbfixerVersion === 'string' &&
    (item.serviceVersion === undefined || typeof item.serviceVersion === 'string')
}

export function saveWorkspace(
  dataRoot: string,
  manifest: WorkspaceManifest,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
): WorkspaceManifestV2 {
  const secured = manifestV2(manifest, legacyOwnerPrincipalId)
  return withWorkspaceManifestLock(dataRoot, manifest.id, () => {
    if (fs.existsSync(workspaceDeletionMarker(dataRoot, manifest.id))) {
      completePendingWorkspaceDeletionUnlocked(dataRoot, manifest.id)
      throw new WorkspaceRevisionConflictError(0, secured.revision)
    }
    const root = workspaceRoot(dataRoot, manifest.id)
    const file = manifestPath(dataRoot, manifest.id)
    let revision = 0
    if (fs.existsSync(file)) {
      const current = readWorkspace(dataRoot, manifest.id, legacyOwnerPrincipalId).workspace
      assertWorkspaceRevision(current, secured.revision)
      revision = current.revision
    } else if (secured.revision !== 0) {
      throw new WorkspaceRevisionConflictError(0, secured.revision)
    }
    fs.mkdirSync(path.join(root, 'files'), { recursive: true })
    fs.mkdirSync(path.join(root, 'runs'), { recursive: true })
    fs.mkdirSync(path.join(root, 'homology'), { recursive: true })
    return publishWorkspaceUnlocked(root, file, secured, revision)
  })
}

function publishWorkspaceUnlocked(
  root: string,
  file: string,
  manifest: WorkspaceManifestV2,
  revision: number,
): WorkspaceManifestV2 {
  const next: WorkspaceManifestV2 = {
    ...manifest,
    version: 2,
    revision: revision + 1,
    updatedAt: new Date().toISOString(),
  }
  const existingBytes = fs.existsSync(file) ? fs.lstatSync(file).size : 0
  assertWorkspaceQuota(root, Math.max(0, jsonByteLength(next) - existingBytes))
  writeJsonAtomic(file, next)
  return next
}

export function updateWorkspace(
  dataRoot: string,
  id: string,
  mutate: (current: WorkspaceManifestV2) => WorkspaceManifest,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
): WorkspaceManifestV2 {
  return withWorkspaceManifestLock(dataRoot, id, () => {
    const current = readWorkspace(dataRoot, id, legacyOwnerPrincipalId).workspace
    const candidate = manifestV2(mutate(current), legacyOwnerPrincipalId)
    if (candidate.id !== current.id || candidate.ownerPrincipalId !== current.ownerPrincipalId) {
      throw new Error('workspace mutation cannot change immutable identity or owner')
    }
    return publishWorkspaceUnlocked(
      workspaceRoot(dataRoot, id),
      manifestPath(dataRoot, id),
      candidate,
      current.revision,
    )
  })
}

export function deleteWorkspace(
  dataRoot: string,
  id: string,
  principalId: string,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
): void {
  withWorkspaceManifestLock(dataRoot, id, () => {
    if (completePendingWorkspaceDeletionUnlocked(dataRoot, id)) return
    const workspace = readWorkspace(dataRoot, id, legacyOwnerPrincipalId).workspace
    assertWorkspaceAccess(workspace, principalId, 'owner')
    const trashName = `${safeId(id)}-${new Date().toISOString().replace(/[:.]/g, '-')}`
    const marker = workspaceDeletionMarker(dataRoot, id)
    writeJsonAtomic(marker, { workspaceId: id, trashName, deletedAt: new Date().toISOString() })
    try {
      completePendingWorkspaceDeletionUnlocked(dataRoot, id)
    } catch (error) {
      fs.rmSync(marker, { force: true })
      throw error
    }
  })
}

export function deleteWorkspaceArtifact(
  dataRoot: string,
  id: string,
  artifactId: string,
  principalId: string,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
): boolean {
  return withWorkspaceManifestLock(dataRoot, id, () => {
    const workspace = readWorkspace(dataRoot, id, legacyOwnerPrincipalId).workspace
    assertWorkspaceAccess(workspace, principalId, 'writer')
    const artifactIndex = workspace.artifacts.findIndex(artifact => artifact.id === artifactId)
    if (artifactIndex < 0) return false
    const artifact = workspace.artifacts[artifactIndex]
    if (isProtectedArtifactPath(artifact.file)) {
      throw new WorkspaceArtifactMutationError('protected workspace metadata cannot be deleted')
    }
    const root = workspaceRoot(dataRoot, id)
    const source = path.resolve(root, artifact.file)
    const relativeSource = path.relative(root, source)
    if (relativeSource.startsWith('..') || path.isAbsolute(relativeSource)) {
      throw new WorkspaceArtifactMutationError(`invalid workspace path: ${artifact.file}`)
    }
    let destination: string | null = null
    if (fs.existsSync(source)) {
      const trash = path.join(root, '.trash')
      fs.mkdirSync(trash, { recursive: true })
      destination = path.join(trash, `${Date.now()}-${crypto.randomUUID()}-${path.basename(source)}`)
      fs.renameSync(source, destination)
    }
    workspace.artifacts.splice(artifactIndex, 1)
    if (workspace.primaryFile === artifact.file) workspace.primaryFile = null
    if (workspace.secondaryFile === artifact.file) workspace.secondaryFile = null
    try {
      publishWorkspaceUnlocked(root, manifestPath(dataRoot, id), workspace, workspace.revision)
    } catch (error) {
      if (destination && fs.existsSync(destination) && !fs.existsSync(source)) {
        fs.renameSync(destination, source)
      }
      throw error
    }
    return true
  })
}

export function resolveWorkspaceFile(dataRoot: string, workspaceId: string, relative: string): string {
  if (!relative || path.isAbsolute(relative)) throw new Error(`invalid workspace path: ${relative}`)
  const root = workspaceRoot(dataRoot, workspaceId)
  const resolved = path.resolve(root, relative)
  const rel = path.relative(root, resolved)
  if (rel.startsWith('..') || path.isAbsolute(rel) || !fs.existsSync(resolved)) {
    throw new Error(`workspace artifact not found: ${relative}`)
  }
  if (!existingRealPathInside(workspacesRoot(dataRoot), root)) {
    throw new Error(`workspace artifact not found: ${relative}`)
  }
  const realResolved = existingRealPathInside(root, resolved)
  if (!realResolved) {
    throw new Error(`workspace artifact not found: ${relative}`)
  }
  return realResolved
}

export function mergeClientWorkspaceUpdate(current: WorkspaceManifest, incoming: WorkspaceManifest): WorkspaceManifest {
  const existing = new Map(current.artifacts.map(artifact => [artifact.id, artifact]))
  const artifacts: WorkspaceArtifact[] = []
  const seen = new Set<string>()
  for (const candidate of Array.isArray(incoming.artifacts) ? incoming.artifacts : []) {
    const artifact = candidate && existing.get(candidate.id)
    if (!artifact || candidate.file !== artifact.file || seen.has(artifact.id)) continue
    artifacts.push(artifact)
    seen.add(artifact.id)
  }
  for (const artifact of current.artifacts) if (!seen.has(artifact.id)) artifacts.push(artifact)
  const structureFiles = new Set(artifacts.filter(artifact => artifact.kind === 'structure').map(artifact => artifact.file))
  const selectedFile = (value: unknown): string | null =>
    typeof value === 'string' && structureFiles.has(value) ? value : null
  return {
    ...current,
    artifacts,
    primaryFile: selectedFile(incoming.primaryFile),
    secondaryFile: selectedFile(incoming.secondaryFile),
    toolState: incoming.toolState && typeof incoming.toolState === 'object' ? incoming.toolState : current.toolState,
  }
}

export function assertWorkspaceRevision(current: WorkspaceManifest, received: unknown): void {
  if (!Number.isSafeInteger(received) || received !== current.revision) {
    throw new WorkspaceRevisionConflictError(current.revision, received)
  }
}

function selectedStructureFile(
  artifacts: WorkspaceArtifact[],
  value: unknown,
  field: 'primaryFile' | 'secondaryFile',
): string | null {
  if (value === null) return null
  if (typeof value === 'string' && artifacts.some(artifact => artifact.kind === 'structure' && artifact.file === value)) {
    return value
  }
  const error = new Error(`${field} must reference an existing structure artifact`) as Error & { statusCode: number }
  error.statusCode = 400
  throw error
}

export function applyWorkspacePatch(current: WorkspaceManifest, patch: WorkspacePatch): WorkspaceManifest {
  assertWorkspaceRevision(current, patch.revision)
  const allowed = new Set(['revision', 'toolState', 'primaryFile', 'secondaryFile', 'artifactOrder'])
  const unknown = Object.keys(patch).find(key => !allowed.has(key))
  if (unknown) {
    const error = new Error(`unsupported workspace patch field: ${unknown}`) as Error & { statusCode: number }
    error.statusCode = 400
    throw error
  }
  if (patch.toolState !== undefined &&
      (!patch.toolState || typeof patch.toolState !== 'object' || Array.isArray(patch.toolState))) {
    const error = new Error('toolState must be an object') as Error & { statusCode: number }
    error.statusCode = 400
    throw error
  }
  let artifacts = current.artifacts
  if (patch.artifactOrder !== undefined) {
    if (!Array.isArray(patch.artifactOrder) || patch.artifactOrder.some(id => typeof id !== 'string')) {
      const error = new Error('artifactOrder must be an array of artifact ids') as Error & { statusCode: number }
      error.statusCode = 400
      throw error
    }
    const byId = new Map(current.artifacts.map(artifact => [artifact.id, artifact]))
    const seen = new Set<string>()
    artifacts = patch.artifactOrder.flatMap(id => {
      const artifact = byId.get(id)
      if (!artifact || seen.has(id)) return []
      seen.add(id)
      return [artifact]
    })
    artifacts.push(...current.artifacts.filter(artifact => !seen.has(artifact.id)))
  }
  return {
    ...current,
    artifacts,
    toolState: patch.toolState === undefined
      ? current.toolState : patch.toolState,
    primaryFile: patch.primaryFile === undefined
      ? current.primaryFile : selectedStructureFile(artifacts, patch.primaryFile, 'primaryFile'),
    secondaryFile: patch.secondaryFile === undefined
      ? current.secondaryFile : selectedStructureFile(artifacts, patch.secondaryFile, 'secondaryFile'),
  }
}

export function applyWorkspaceAclPatch(
  current: WorkspaceManifestV2,
  principalId: string,
  patch: WorkspaceAclPatch,
): WorkspaceManifestV2 {
  assertWorkspaceAccess(current, principalId, 'owner')
  assertWorkspaceRevision(current, patch.revision)
  const unknown = Object.keys(patch).find(key => key !== 'revision' && key !== 'acl')
  if (unknown) {
    const error = new Error(`unsupported workspace ACL patch field: ${unknown}`) as Error & { statusCode: number }
    error.statusCode = 400
    throw error
  }
  validateAcl(current.ownerPrincipalId, patch.acl)
  return { ...current, acl: patch.acl.map(entry => ({ ...entry })) }
}

export function applyArtifactMetadataPatch(
  current: WorkspaceManifest,
  artifactId: string,
  patch: WorkspaceArtifactMetadataPatch,
): WorkspaceManifest {
  assertWorkspaceRevision(current, patch.revision)
  const allowed = new Set(['revision', 'name', ...STRING_METADATA_FIELDS, 'equivalentChains'])
  const unknown = Object.keys(patch).find(key => !allowed.has(key))
  if (unknown) {
    const error = new Error(`unsupported artifact metadata field: ${unknown}`) as Error & { statusCode: number }
    error.statusCode = 400
    throw error
  }
  const artifact = current.artifacts.find(candidate => candidate.id === artifactId)
  if (!artifact) {
    const error = new Error(`artifact not found: ${artifactId}`) as Error & { statusCode: number }
    error.statusCode = 404
    throw error
  }
  if (patch.name !== undefined) {
    if (typeof patch.name !== 'string' || !patch.name.trim()) {
      const error = new Error('artifact name must be a non-empty string') as Error & { statusCode: number }
      error.statusCode = 400
      throw error
    }
    artifact.name = patch.name.trim()
  }
  for (const field of STRING_METADATA_FIELDS) {
    const value = patch[field]
    if (value === undefined) continue
    if (value === null) delete artifact[field]
    else if (typeof value === 'string' || (field === 'resolution' && typeof value === 'number')) {
      Object.assign(artifact, { [field]: String(value) })
    } else {
      const error = new Error(`${field} must be a string or null`) as Error & { statusCode: number }
      error.statusCode = 400
      throw error
    }
  }
  if (patch.equivalentChains !== undefined) {
    if (patch.equivalentChains === null) delete artifact.equivalentChains
    else if (validEquivalentChains(patch.equivalentChains)) {
      artifact.equivalentChains = patch.equivalentChains.map(group => [...group])
    } else {
      const error = new Error('equivalentChains must be string[][] or null') as Error & { statusCode: number }
      error.statusCode = 400
      throw error
    }
  }
  return current
}

export function artifactResponseHeaders(filename: string): Record<string, string> {
  const extension = path.extname(filename).toLowerCase()
  const activeContent = extension === '.html' || extension === '.xml'
  return {
    'Content-Type': CONTENT_TYPES[extension] || 'application/octet-stream',
    'Content-Disposition': `${activeContent ? 'attachment' : 'inline'}; filename="${filename.replace(/["\\]/g, '_')}"`,
    'X-Content-Type-Options': 'nosniff',
    ...(activeContent ? { 'Content-Security-Policy': "sandbox; default-src 'none'" } : {}),
  }
}

function uniqueId(name: string): string {
  const stem = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'workspace'
  return `${stem}-${crypto.randomUUID().slice(0, 8)}`
}

function artifactFor(file: string, folder?: string): WorkspaceArtifact {
  const extension = path.extname(file).toLowerCase()
  const structure = ['.pdb', '.cif', '.mmcif', '.gro'].includes(extension)
  const basename = path.basename(file)
  return {
    id: crypto.randomUUID(), file: file.replace(/\\/g, '/'),
    name: path.basename(file, extension), kind: structure ? 'structure' : 'artifact', folder,
    hidden: ['workspace.json', 'index.json', 'run.json', 'stdout.log', 'stderr.log'].includes(basename) || basename.startsWith('_'),
  }
}

function legacyMetadata(entry: Record<string, unknown>): Partial<WorkspaceArtifact> {
  const metadata: Partial<WorkspaceArtifact> = {}
  for (const field of STRING_METADATA_FIELDS) {
    const value = entry[field]
    if (typeof value === 'string') metadata[field] = value
    else if (field === 'resolution' && typeof value === 'number') metadata.resolution = String(value)
  }
  if (validEquivalentChains(entry.equivalentChains)) metadata.equivalentChains = entry.equivalentChains
  return metadata
}

export function createWorkspace(
  dataRoot: string,
  name: string,
  ownerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
  provisionalOwner = false,
): WorkspaceManifestV2 {
  if (!validPrincipalId(ownerPrincipalId)) throw new Error('invalid workspace ownerPrincipalId')
  const now = new Date().toISOString()
  return saveWorkspace(dataRoot, {
    version: 2, revision: 0, id: uniqueId(name), name, createdAt: now, updatedAt: now,
    primaryFile: null, secondaryFile: null, artifacts: [], toolState: {},
    ownerPrincipalId, acl: [], ...(provisionalOwner ? { provisionalOwner: true } : {}),
  })
}

/**
 * One-time compatibility migration. Files are copied before manifests are
 * published, so a failed migration never damages the legacy library.
 */
function ensureWorkspaceMigrationUnlocked(
  dataRoot: string,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
  provisionalLocalOwner = false,
): void {
  const marker = path.join(workspacesRoot(dataRoot), '.migrated-v1')
  if (fs.existsSync(marker)) return
  const indexFile = path.join(dataRoot, 'index.json')
  let entries: any[] = []
  if (fs.existsSync(indexFile)) {
    try { entries = JSON.parse(fs.readFileSync(indexFile, 'utf8')) } catch { entries = [] }
  }
  const folders = entries.filter(entry => entry.kind === 'folder')
  const root = folders.find(entry => entry.id === '__root__')
  const byId = new Map(entries.map(entry => [entry.kind === 'folder' ? entry.id : entry.file, entry]))
  const assigned = new Set<string>()

  const collect = (id: string, prefix = ''): Array<{ entry: any; folder: string }> => {
    const entry = byId.get(id)
    if (!entry) return []
    if (entry.kind !== 'folder') return [{ entry, folder: prefix }]
    const nextPrefix = entry.id === '__root__' ? prefix : [prefix, entry.name].filter(Boolean).join('/')
    return (entry.children || []).flatMap((child: string) => collect(child, nextPrefix))
  }

  const groups: Array<{ name: string; files: Array<{ entry: any; folder: string }> }> = []
  for (const child of root?.children || []) {
    const entry = byId.get(child)
    if (entry?.kind === 'folder') groups.push({ name: entry.name, files: (entry.children || []).flatMap((nested: string) => collect(nested, '')) })
  }
  const explicitlyGrouped = new Set(groups.flatMap(group => group.files.map(item => item.entry.file)))
  const remaining = entries.filter(entry => entry.kind !== 'folder' && !explicitlyGrouped.has(entry.file))
    .map(entry => ({ entry, folder: '' }))
  if (remaining.length || groups.length === 0) groups.push({ name: 'Unsorted', files: remaining })

  const ownership = new Map<string, { workspaceId: string; relative: string }>()
  const createdWorkspaceIds: string[] = []
  for (const group of groups) {
    const workspace = createWorkspace(
      dataRoot, group.name, legacyOwnerPrincipalId,
      provisionalLocalOwner && legacyOwnerPrincipalId === LOCAL_WORKSPACE_PRINCIPAL_ID,
    )
    createdWorkspaceIds.push(workspace.id)
    const artifacts: WorkspaceArtifact[] = []
    for (const { entry, folder } of group.files) {
      if (!entry.file || assigned.has(entry.file)) continue
      const source = path.resolve(dataRoot, entry.file)
      const realSource = existingRealPathInside(dataRoot, source)
      if (!realSource || !fs.statSync(realSource).isFile()) continue
      assigned.add(entry.file)
      const relative = path.join('files', folder, path.basename(entry.file)).replace(/\\/g, '/')
      const destination = path.join(workspaceRoot(dataRoot, workspace.id), relative)
      fs.mkdirSync(path.dirname(destination), { recursive: true })
      fs.copyFileSync(realSource, destination)
      ownership.set(entry.file, { workspaceId: workspace.id, relative })
      artifacts.push({
        ...artifactFor(relative, folder || undefined), ...legacyMetadata(entry),
        name: entry.name || artifactFor(relative).name, legacySourceFile: entry.file,
        parent: entry.parent, command: entry.command, artifactType: entry.artifactType,
      })
    }
    saveWorkspace(dataRoot, { ...workspace, artifacts, primaryFile: artifacts.find(a => a.kind === 'structure')?.file || null })
  }

  const legacyHomology = path.join(dataRoot, 'homology_projects')
  if (fs.existsSync(legacyHomology)) {
    for (const directory of fs.readdirSync(legacyHomology, { withFileTypes: true }).filter(entry => entry.isDirectory())) {
      const sourceProject = path.join(legacyHomology, directory.name, 'homology-project.json')
      if (!fs.existsSync(sourceProject)) continue
      try {
        const project = JSON.parse(fs.readFileSync(sourceProject, 'utf8')) as { id: string; templates?: Array<{ file: string }> }
        const counts = new Map<string, number>()
        for (const template of project.templates || []) {
          const owner = ownership.get(template.file)
          if (owner) counts.set(owner.workspaceId, (counts.get(owner.workspaceId) || 0) + 1)
        }
        const targetId = [...counts].sort((a, b) => b[1] - a[1])[0]?.[0] || createdWorkspaceIds[0]
        if (!targetId) continue
        const targetWorkspace = loadWorkspace(dataRoot, targetId, legacyOwnerPrincipalId)
        for (const template of project.templates || []) {
          const owner = ownership.get(template.file)
          if (owner?.workspaceId === targetId) { template.file = owner.relative; continue }
          const legacySource = path.resolve(dataRoot, template.file)
          const realLegacySource = existingRealPathInside(dataRoot, legacySource)
          if (!realLegacySource || !fs.statSync(realLegacySource).isFile()) continue
          const relative = path.join('files', 'legacy_homology', path.basename(template.file)).replace(/\\/g, '/')
          const destination = path.join(workspaceRoot(dataRoot, targetId), relative)
          fs.mkdirSync(path.dirname(destination), { recursive: true })
          fs.copyFileSync(realLegacySource, destination)
          template.file = relative
          if (!targetWorkspace.artifacts.some(artifact => artifact.file === relative)) targetWorkspace.artifacts.push(artifactFor(relative, 'legacy_homology'))
        }
        const destination = path.join(workspaceRoot(dataRoot, targetId), 'homology', safeId(project.id), 'homology-project.json')
        fs.mkdirSync(path.dirname(destination), { recursive: true })
        writeJsonAtomic(destination, project)
        saveWorkspace(dataRoot, targetWorkspace)
      } catch { /* keep malformed legacy workflows untouched */ }
    }
  }
  fs.writeFileSync(marker, `${new Date().toISOString()}\n`)
}

export function ensureWorkspaceMigration(
  dataRoot: string,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
  provisionalLocalOwner = false,
): void {
  withGlobalMigrationLock(dataRoot, () => {
    ensureWorkspaceMigrationUnlocked(dataRoot, legacyOwnerPrincipalId, provisionalLocalOwner)
  })
}

/** One-time, non-destructive import for installations migrated before artifact metadata existed. */
function ensureWorkspaceMetadataMigrationUnlocked(
  dataRoot: string,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
  provisionalLocalOwner = false,
): void {
  ensureWorkspaceMigrationUnlocked(dataRoot, legacyOwnerPrincipalId, provisionalLocalOwner)
  const marker = path.join(workspacesRoot(dataRoot), '.metadata-migrated-v1')
  if (fs.existsSync(marker)) return
  const index = path.join(dataRoot, 'index.json')
  let entries: Array<Record<string, unknown>> = []
  if (fs.existsSync(index)) {
    try {
      const parsed = JSON.parse(fs.readFileSync(index, 'utf8'))
      if (Array.isArray(parsed)) entries = parsed.filter(entry =>
        !!entry && typeof entry === 'object' && entry.kind !== 'folder' && typeof entry.file === 'string')
    } catch { entries = [] }
  }
  const byBasename = new Map<string, Array<Record<string, unknown>>>()
  for (const entry of entries) {
    const basename = path.basename(String(entry.file))
    byBasename.set(basename, [...(byBasename.get(basename) || []), entry])
  }
  for (const directory of fs.readdirSync(workspacesRoot(dataRoot), { withFileTypes: true }).filter(entry => entry.isDirectory())) {
    let workspace: WorkspaceManifest
    try { workspace = loadWorkspace(dataRoot, directory.name, legacyOwnerPrincipalId) } catch { continue }
    let changed = false
    for (const artifact of workspace.artifacts) {
      const exact = entries.filter(entry => {
        const legacyFile = String(entry.file)
        return artifact.legacySourceFile === legacyFile || artifact.file === legacyFile || artifact.file.endsWith(`/${legacyFile}`)
      })
      const basenameMatches = byBasename.get(path.basename(artifact.file)) || []
      const matches = exact.length === 1 ? exact : (exact.length === 0 && basenameMatches.length === 1 ? basenameMatches : [])
      if (matches.length !== 1) continue
      const metadata = legacyMetadata(matches[0])
      for (const [key, value] of Object.entries(metadata)) {
        const field = key as keyof WorkspaceArtifact
        if (artifact[field] === undefined) {
          Object.assign(artifact, { [field]: value })
          changed = true
        }
      }
      if (!artifact.legacySourceFile) {
        artifact.legacySourceFile = String(matches[0].file)
        changed = true
      }
    }
    if (changed) saveWorkspace(dataRoot, workspace)
  }
  fs.writeFileSync(marker, `${new Date().toISOString()}\n`)
}

export function ensureWorkspaceMetadataMigration(
  dataRoot: string,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
  provisionalLocalOwner = false,
): void {
  withGlobalMigrationLock(dataRoot, () => {
    ensureWorkspaceMetadataMigrationUnlocked(dataRoot, legacyOwnerPrincipalId, provisionalLocalOwner)
  })
}

/** Import per-workspace runtime indexes created by older GUI releases. */
function ensureRetiredWorkspaceIndexMigrationUnlocked(
  dataRoot: string,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
  provisionalLocalOwner = false,
): void {
  ensureWorkspaceMetadataMigrationUnlocked(dataRoot, legacyOwnerPrincipalId, provisionalLocalOwner)
  const marker = path.join(workspacesRoot(dataRoot), '.artifact-index-migrated-v1')
  if (fs.existsSync(marker)) return
  for (const directory of fs.readdirSync(workspacesRoot(dataRoot), { withFileTypes: true }).filter(entry => entry.isDirectory())) {
    const index = path.join(workspaceRoot(dataRoot, directory.name), 'index.json')
    if (!fs.existsSync(index)) continue
    let entries: Array<Record<string, any>> = []
    try {
      const parsed = JSON.parse(fs.readFileSync(index, 'utf8'))
      if (Array.isArray(parsed)) entries = parsed.filter(entry => entry && typeof entry.file === 'string' && entry.kind !== 'folder')
    } catch { continue }
    const workspace = loadWorkspace(dataRoot, directory.name, legacyOwnerPrincipalId)
    let changed = false
    for (const entry of entries) {
      if (isProtectedArtifactPath(entry.file)) continue
      const file = existingRealPathInside(workspaceRoot(dataRoot, workspace.id), path.resolve(workspaceRoot(dataRoot, workspace.id), entry.file))
      if (!file || !fs.statSync(file).isFile()) continue
      let artifact = workspace.artifacts.find(item => item.file === entry.file)
      if (!artifact) {
        artifact = artifactFor(entry.file)
        workspace.artifacts.push(artifact)
        changed = true
      }
      const migrated = {
        ...legacyMetadata(entry),
        ...(typeof entry.parent === 'string' ? { parent: entry.parent } : {}),
        ...(typeof entry.command === 'string' ? { command: entry.command } : {}),
        ...(typeof entry._engineerChecksum === 'string' ? { engineerChecksum: entry._engineerChecksum } : {}),
        ...(Array.isArray(entry.mutationIds) && entry.mutationIds.every((id: unknown) => Number.isInteger(id)) ? { mutationIds: entry.mutationIds } : {}),
        ...(typeof entry.mutationsResolved === 'string' ? { mutationsResolved: entry.mutationsResolved } : {}),
        ...(typeof entry.hasGlycan === 'boolean' ? { hasGlycan: entry.hasGlycan } : {}),
        ...(entry.scheme === 'EU' || entry.scheme === 'Kabat' ? { scheme: entry.scheme } : {}),
      }
      for (const [key, value] of Object.entries(migrated)) {
        if ((artifact as any)[key] === undefined) {
          Object.assign(artifact, { [key]: value })
          changed = true
        }
      }
    }
    if (changed) saveWorkspace(dataRoot, workspace)
  }
  fs.writeFileSync(marker, `${new Date().toISOString()}\n`)
}

export function ensureRetiredWorkspaceIndexMigration(
  dataRoot: string,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
  provisionalLocalOwner = false,
): void {
  withGlobalMigrationLock(dataRoot, () => {
    ensureRetiredWorkspaceIndexMigrationUnlocked(dataRoot, legacyOwnerPrincipalId, provisionalLocalOwner)
  })
}

function allWorkspaces(
  dataRoot: string,
  legacyOwnerPrincipalId: string,
  principalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
): WorkspaceManifestV2[] {
  const workspaces = fs.readdirSync(workspacesRoot(dataRoot), { withFileTypes: true })
    .filter(entry => entry.isDirectory())
    .flatMap(entry => { try { return [loadWorkspace(dataRoot, entry.name, legacyOwnerPrincipalId)] } catch { return [] } })
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt) || a.name.localeCompare(b.name))
  const order = readWorkspaceOrder(dataRoot, principalId)
  const positions = new Map(order.map((id, index) => [id, index]))
  return workspaces.sort((a, b) => {
    const ai = positions.get(a.id)
    const bi = positions.get(b.id)
    if (ai !== undefined && bi !== undefined) return ai - bi
    if (ai !== undefined) return -1
    if (bi !== undefined) return 1
    return 0
  })
}

export function listWorkspaces(
  dataRoot: string,
  principalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
): WorkspaceManifestV2[] {
  ensureRetiredWorkspaceIndexMigration(dataRoot, legacyOwnerPrincipalId)
  return allWorkspaces(dataRoot, legacyOwnerPrincipalId, principalId)
    .filter(workspace => canReadWorkspace(workspace, principalId))
}

export function reorderWorkspaces(
  dataRoot: string,
  ids: string[],
  principalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
): string[] {
  ensureRetiredWorkspaceIndexMigration(dataRoot, legacyOwnerPrincipalId)
  const workspaces = allWorkspaces(dataRoot, legacyOwnerPrincipalId, principalId)
  const existing = new Set(workspaces.map(workspace => workspace.id))
  const readable = new Set(workspaces.filter(workspace => canReadWorkspace(workspace, principalId)).map(workspace => workspace.id))
  const requested = ids.filter((id, index) => readable.has(id) && ids.indexOf(id) === index)
  for (const workspace of workspaces) if (readable.has(workspace.id) && !requested.includes(workspace.id)) requested.push(workspace.id)

  const stored = readWorkspaceOrder(dataRoot, principalId)
    .filter((id, index, values) => existing.has(id) && values.indexOf(id) === index)
  for (const workspace of workspaces) if (!stored.includes(workspace.id)) stored.push(workspace.id)
  const nextVisible = requested[Symbol.iterator]()
  const merged = stored.map(id => readable.has(id) ? nextVisible.next().value as string : id)
  writeWorkspaceOrder(dataRoot, merged, principalId)
  return requested
}

export function registerWorkspaceApi(
  server: ApiRouteHost,
  dataRoot: string,
  principalSource: string | ((request: IncomingMessage) => string) = LOCAL_WORKSPACE_PRINCIPAL_ID,
  legacyOwnerPrincipalId = LOCAL_WORKSPACE_PRINCIPAL_ID,
  provisionalLocalOwner = false,
): void {
  reconcilePendingWorkspaceDeletions(dataRoot)
  ensureRetiredWorkspaceIndexMigration(dataRoot, legacyOwnerPrincipalId, provisionalLocalOwner)
  server.middlewares.use('/api/workspaces', async (req, res, next) => {
    try {
      const principalId = typeof principalSource === 'function' ? principalSource(req) : principalSource
      const parts = (req.url || '').split('?')[0].split('/').filter(Boolean).map(decodeURIComponent)
      if (!parts.length && req.method === 'GET') {
        return sendJson(res, 200, listWorkspaces(dataRoot, principalId, legacyOwnerPrincipalId).map(workspace => ({
          id: workspace.id,
          name: workspace.name,
          updatedAt: workspace.updatedAt,
          artifactCount: workspace.artifacts.filter(artifact => !artifact.hidden).length,
          effectiveRole: workspaceRole(workspace, principalId),
        })))
      }
      if (!parts.length && req.method === 'POST') {
        const body = JSON.parse((await readRequestBody(req)).toString('utf8') || '{}')
        const workspace = createWorkspace(
          dataRoot,
          String(body.name || 'Untitled workspace'),
          principalId,
          provisionalLocalOwner && principalId === LOCAL_WORKSPACE_PRINCIPAL_ID,
        )
        writeWorkspaceOrder(
          dataRoot,
          [workspace.id, ...readWorkspaceOrder(dataRoot, principalId).filter(id => id !== workspace.id)],
          principalId,
        )
        return sendJson(res, 201, workspaceView(workspace, principalId))
      }
      if (parts[0] === 'order' && req.method === 'PATCH') {
        const body = JSON.parse((await readRequestBody(req)).toString('utf8') || '{}') as { ids?: string[] }
        const ids = reorderWorkspaces(dataRoot, body.ids || [], principalId, legacyOwnerPrincipalId)
        return sendJson(res, 200, { ids })
      }
      const id = parts[0]
      if (parts.length === 1 && req.method === 'GET') {
        const workspace = loadWorkspace(dataRoot, id, legacyOwnerPrincipalId)
        assertWorkspaceAccess(workspace, principalId)
        return sendJson(res, 200, workspaceView(workspace, principalId))
      }
      if (parts.length === 1 && req.method === 'DELETE') {
        deleteWorkspace(dataRoot, id, principalId, legacyOwnerPrincipalId)
        res.statusCode = 204
        return res.end()
      }
      if (parts.length === 1 && req.method === 'PUT') {
        const incoming = JSON.parse((await readRequestBody(req)).toString('utf8')) as WorkspaceManifest
        const current = loadWorkspace(dataRoot, id, legacyOwnerPrincipalId)
        assertWorkspaceAccess(current, principalId, 'writer')
        assertWorkspaceRevision(current, incoming.revision)
        return sendJson(res, 200, workspaceView(
          saveWorkspace(dataRoot, mergeClientWorkspaceUpdate(current, incoming)), principalId,
        ))
      }
      if (parts.length === 1 && req.method === 'PATCH') {
        const patch = JSON.parse((await readRequestBody(req)).toString('utf8')) as WorkspacePatch
        const current = loadWorkspace(dataRoot, id, legacyOwnerPrincipalId)
        assertWorkspaceAccess(current, principalId, 'writer')
        return sendJson(res, 200, workspaceView(
          saveWorkspace(dataRoot, applyWorkspacePatch(current, patch)), principalId,
        ))
      }
      if (parts[1] === 'acl' && parts.length === 2 && req.method === 'PATCH') {
        const patch = JSON.parse((await readRequestBody(req)).toString('utf8') || '{}') as WorkspaceAclPatch
        const current = loadWorkspace(dataRoot, id, legacyOwnerPrincipalId)
        return sendJson(res, 200, workspaceView(
          saveWorkspace(dataRoot, applyWorkspaceAclPatch(current, principalId, patch)), principalId,
        ))
      }
      if (parts[1] === 'download' && req.method === 'GET') {
        const workspace = loadWorkspace(dataRoot, id, legacyOwnerPrincipalId)
        assertWorkspaceAccess(workspace, principalId)
        const filename = `${workspace.name.replace(/[^a-zA-Z0-9._-]+/g, '_') || 'workspace'}.tar.gz`
        res.statusCode = 200
        res.setHeader('Content-Type', 'application/gzip')
        res.setHeader('Content-Disposition', `attachment; filename="${filename}"`)
        res.setHeader('X-Content-Type-Options', 'nosniff')
        return Readable.from(workspaceArchive(dataRoot, workspace)).pipe(zlib.createGzip()).pipe(res)
      }
      if (parts[1] === 'rename' && req.method === 'PATCH') {
        const body = JSON.parse((await readRequestBody(req)).toString('utf8') || '{}')
        const name = String(body.name || '').trim()
        if (!name) return sendJson(res, 400, { error: 'workspace name cannot be empty' })
        const workspace = loadWorkspace(dataRoot, id, legacyOwnerPrincipalId)
        assertWorkspaceAccess(workspace, principalId, 'writer')
        return sendJson(res, 200, workspaceView(saveWorkspace(dataRoot, { ...workspace, name }), principalId))
      }
      if (parts[1] === 'import' && req.method === 'POST') {
        assertWorkspaceAccess(
          loadWorkspace(dataRoot, id, legacyOwnerPrincipalId), principalId, 'writer',
        )
        const encoded = Array.isArray(req.headers['x-file-name']) ? req.headers['x-file-name'][0] : req.headers['x-file-name']
        const original = decodeURIComponent(encoded || '')
        const safe = path.basename(original).replace(/[^a-zA-Z0-9._-]+/g, '_')
        if (!safe || !ALLOWED.has(path.extname(safe).toLowerCase())) return sendJson(res, 400, { error: `unsupported artifact type: ${original}` })
        if (isProtectedArtifactPath(safe)) return sendJson(res, 400, { error: 'reserved workspace metadata filename' })
        const content = await readRequestBody(req, storageQuotaSettings().maxUploadBytes)
        if (!content.length) return sendJson(res, 400, { error: 'uploaded artifact is empty' })
        const workspace = loadWorkspace(dataRoot, id, legacyOwnerPrincipalId)
        assertWorkspaceAccess(workspace, principalId, 'writer')
        const root = workspaceRoot(dataRoot, id)
        const directory = path.join(root, 'files', 'imports')
        fs.mkdirSync(directory, { recursive: true })
        let destination = path.join(directory, safe)
        if (fs.existsSync(destination)) destination = path.join(directory, `${path.basename(safe, path.extname(safe))}_${Date.now()}${path.extname(safe)}`)
        const relative = path.relative(root, destination).replace(/\\/g, '/')
        const artifact = artifactFor(relative, 'imports')
        const nextManifest = { ...workspace, artifacts: [...workspace.artifacts, artifact] }
        assertWorkspaceQuota(root, content.length)
        let published = false
        try {
          writeBufferAtomic(destination, content)
          published = true
          saveWorkspace(dataRoot, nextManifest)
        } catch (error) {
          if (published) {
            try { fs.unlinkSync(destination) } catch { /* best-effort cleanup */ }
          }
          throw error
        }
        return sendJson(res, 201, artifact)
      }
      if (parts[1] === 'artifacts' && parts[2] && req.method === 'DELETE') {
        if (!deleteWorkspaceArtifact(dataRoot, id, parts[2], principalId, legacyOwnerPrincipalId)) {
          return sendJson(res, 404, { error: `artifact not found: ${parts[2]}` })
        }
        res.statusCode = 204
        return res.end()
      }
      if (parts[1] === 'artifacts' && parts[2] && parts[3] === 'rename' && req.method === 'PATCH') {
        const workspace = loadWorkspace(dataRoot, id, legacyOwnerPrincipalId)
        assertWorkspaceAccess(workspace, principalId, 'writer')
        return sendJson(res, 410, { error: 'use the revisioned artifact metadata endpoint' })
      }
      if (parts[1] === 'artifacts' && parts[2] && parts[3] === 'metadata' && req.method === 'PATCH') {
        const patch = JSON.parse((await readRequestBody(req)).toString('utf8') || '{}') as WorkspaceArtifactMetadataPatch
        const workspace = loadWorkspace(dataRoot, id, legacyOwnerPrincipalId)
        assertWorkspaceAccess(workspace, principalId, 'writer')
        return sendJson(res, 200, workspaceView(
          saveWorkspace(dataRoot, applyArtifactMetadataPatch(workspace, parts[2], patch)), principalId,
        ))
      }
      if (parts[1] === 'files' && parts.length >= 3 && req.method === 'GET') {
        const workspace = loadWorkspace(dataRoot, id, legacyOwnerPrincipalId)
        assertWorkspaceAccess(workspace, principalId)
        const relative = parts.slice(2).join('/')
        const file = resolveWorkspaceFile(dataRoot, id, relative)
        const filename = path.basename(file)
        for (const [header, value] of Object.entries(artifactResponseHeaders(filename))) res.setHeader(header, value)
        return fs.createReadStream(file).pipe(res)
      }
      return next()
    } catch (error: any) {
      const fallback = /not found/.test(error?.message || '') ? 404 : 500
      const body: Record<string, unknown> = { error: error?.message || String(error) }
      if (error instanceof WorkspaceQuotaExceededError) {
        body.code = error.code
        body.details = error.details
      }
      return sendJson(res, errorStatus(error, fallback), body)
    }
  })
}
