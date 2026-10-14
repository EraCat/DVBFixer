import type { IncomingMessage, ServerResponse } from 'node:http'
import crypto from 'node:crypto'
import { isDeepStrictEqual } from 'node:util'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { readDiffusionPublication } from './diffusion-bundle'
import { runDvbfixerArgs, type DvbfixerRunResult } from './dvbfixer-runner'
import {
  assertWorkspaceAccess, loadWorkspace, updateWorkspace, workspaceRoot, writeJsonAtomic,
} from './workspace-api'
import { errorStatus, readRequestBody } from './request-body'
import { assertWorkspaceQuota } from './storage-quota'
import type { ApiRouteHost } from './http-types'

function assertRunAdmitted(result: DvbfixerRunResult): void {
  if (result.started || (result.failure !== 'overloaded' && result.failure !== 'shutdown')) return
  const error = new Error(result.stderr || 'DVBFixer process admission unavailable') as Error & { statusCode: number }
  error.statusCode = 503
  throw error
}

export interface TemplateSelection {
  id: string
  file: string
  chain: string
  targetChain: string
  label?: string
  fittedFile?: string
}

export interface AlignmentSpan { start: number; end: number }
export interface AlignmentRow {
  id: string
  kind: 'target' | 'template'
  sequence: string
  templateId?: string
}
export interface AlignmentGroup {
  chainId: string
  rows: AlignmentRow[]
  masks: Record<string, AlignmentSpan[]>
  maskModes?: Record<string, 'all' | 'ranges' | 'none'>
}
export interface HomologyProject {
  version: 1
  id: string
  name: string
  targetFasta: string
  templates: TemplateSelection[]
  engine: 'mafft' | 'muscle' | 'clustalo'
  alignmentGroups: AlignmentGroup[]
  structuralAlignment?: string | Record<string, string>
  modelOptions: Record<string, string | number | boolean>
  createdAt: string
  updatedAt: string
}

const AA3: Record<string, string> = {
  ALA: 'A', ARG: 'R', ASN: 'N', ASP: 'D', CYS: 'C', GLN: 'Q', GLU: 'E', GLY: 'G',
  HIS: 'H', ILE: 'I', LEU: 'L', LYS: 'K', MET: 'M', PHE: 'F', PRO: 'P', SER: 'S',
  THR: 'T', TRP: 'W', TYR: 'Y', VAL: 'V', MSE: 'M', HID: 'H', HIE: 'H', HIP: 'H',
  ASH: 'D', GLH: 'E', LYN: 'K', CYX: 'C', CYM: 'C',
}

function sendJson(res: ServerResponse, status: number, body: unknown): void {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(body))
}

function readBody(req: IncomingMessage): Promise<string> {
  return readRequestBody(req).then(body => body.toString('utf8'))
}

function safeId(id: string): string {
  if (!/^[a-zA-Z0-9_-]+$/.test(id)) throw new Error('invalid project id')
  return id
}

function resolveArtifact(root: string, relative: string): string {
  if (!relative || path.isAbsolute(relative)) throw new Error(`invalid artifact path: ${relative}`)
  const resolved = path.resolve(root, relative)
  const rel = path.relative(root, resolved)
  if (rel.startsWith('..') || path.isAbsolute(rel) || !fs.existsSync(resolved)) {
    throw new Error(`artifact not found: ${relative}`)
  }
  const realRoot = fs.realpathSync(root)
  const realResolved = fs.realpathSync(resolved)
  const realRelative = path.relative(realRoot, realResolved)
  if (realRelative.startsWith('..') || path.isAbsolute(realRelative)) {
    throw new Error(`artifact not found: ${relative}`)
  }
  return realResolved
}

const MD_LEVELS = new Set(['none', 'fast', 'slow', 'very_slow', 'slow_large'])
const MODEL_OPTION_FLAGS = new Set([
  '--num-models', '--md-level', '--backend', '--diffusion-model', '--diffusion-seed',
  '--diffusion-context',
  '--diffusion-regenerate-covered',
])

export function validatedModelArgs(options: Record<string, unknown> | null | undefined): string[] {
  const values = options || {}
  const unknown = Object.keys(values).filter(flag => !MODEL_OPTION_FLAGS.has(flag))
  if (unknown.length) throw new Error(`unsupported homology model option: ${unknown[0]}`)
  const args: string[] = []
  const backend = values['--backend'] ?? 'modeller'
  if (backend !== 'modeller' && backend !== 'diffusion') {
    throw new Error('--backend has an unsupported value')
  }
  if (backend === 'diffusion') {
    if (values['--diffusion-model'] !== undefined && values['--diffusion-model'] !== '' &&
        !['protpardelle', 'protenix'].includes(String(values['--diffusion-model']))) {
      throw new Error('--diffusion-model has an unsupported value')
    }
    const seed = values['--diffusion-seed'] ?? 7
    if (typeof seed !== 'number' || !Number.isInteger(seed) || seed < 0) {
      throw new Error('--diffusion-seed must be a non-negative integer')
    }
    args.push('--backend', 'diffusion', '--diffusion-seed', String(seed))
    if (values['--diffusion-model']) args.push('--diffusion-model', String(values['--diffusion-model']))
    if (values['--diffusion-context'] !== undefined && values['--diffusion-context'] !== 'none') {
      if (!['local', 'full'].includes(String(values['--diffusion-context']))) throw new Error('--diffusion-context has an unsupported value')
      args.push('--diffusion-context', String(values['--diffusion-context']))
    }
    if (values['--diffusion-regenerate-covered'] !== undefined) {
      if (typeof values['--diffusion-regenerate-covered'] !== 'boolean') throw new Error('--diffusion-regenerate-covered must be boolean')
      if (values['--diffusion-regenerate-covered']) args.push('--diffusion-regenerate-covered')
    }
  } else if (values['--diffusion-model'] !== undefined || values['--diffusion-seed'] !== undefined || values['--diffusion-context'] !== undefined || values['--diffusion-regenerate-covered'] !== undefined) {
    throw new Error('diffusion model options require --backend diffusion')
  }
  if (backend === 'modeller' && values['--num-models'] !== undefined && values['--num-models'] !== '') {
    const count = values['--num-models']
    if (typeof count !== 'number' || !Number.isInteger(count) || count < 1 || count > 1000) {
      throw new Error('--num-models must be an integer from 1 to 1000')
    }
    args.push('--num-models', String(count))
  }
  if (backend === 'modeller' && values['--md-level'] !== undefined && values['--md-level'] !== '') {
    const level = values['--md-level']
    if (typeof level !== 'string' || !MD_LEVELS.has(level)) {
      throw new Error('--md-level has an unsupported value')
    }
    args.push('--md-level', level)
  }
  return args
}

function normalizedProject(value: unknown, expectedId?: string): HomologyProject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('homology project must be a JSON object')
  const project = value as Partial<HomologyProject>
  if (typeof project.id !== 'string' || !/^[a-zA-Z0-9_-]+$/.test(project.id)) throw new Error('homology project has an invalid id')
  if (expectedId && project.id !== expectedId) throw new Error(`homology project id ${project.id} does not match directory ${expectedId}`)
  if (typeof project.name !== 'string' || typeof project.targetFasta !== 'string') throw new Error('homology project is missing name or targetFasta')
  if (!Array.isArray(project.templates) || !Array.isArray(project.alignmentGroups)) throw new Error('homology project has invalid templates or alignments')
  if (!['mafft', 'muscle', 'clustalo'].includes(String(project.engine))) throw new Error('homology project has an invalid MSA engine')
  if (!project.modelOptions || typeof project.modelOptions !== 'object' || Array.isArray(project.modelOptions)) throw new Error('homology project has invalid model options')
  if (typeof project.createdAt !== 'string' || typeof project.updatedAt !== 'string') throw new Error('homology project is missing timestamps')
  return { ...project, version: 1 } as HomologyProject
}

function readProjectFile(file: string, expectedId?: string): HomologyProject {
  try {
    return normalizedProject(JSON.parse(fs.readFileSync(file, 'utf8')), expectedId)
  } catch (error: any) {
    throw new Error(`invalid homology project ${file}: ${error?.message || String(error)}`)
  }
}

function migrationCandidates(directory: string): string[] {
  if (!fs.existsSync(directory)) return []
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    if (entry.isDirectory()) {
      const nested = path.join(directory, entry.name, 'homology-project.json')
      return fs.existsSync(nested) ? [nested] : []
    }
    return entry.isFile() && entry.name.endsWith('.json') ? [path.join(directory, entry.name)] : []
  })
}

/** Migrate all known per-workspace layouts without overwriting canonical data. */
export function ensureHomologyStorage(root: string): string {
  const canonical = path.join(root, 'homology')
  fs.mkdirSync(canonical, { recursive: true })
  const alternateRoots = [path.join(root, 'homology_projects'), path.join(root, 'homology-projects')]
  const candidates = [
    ...alternateRoots.flatMap(migrationCandidates),
    ...fs.readdirSync(canonical, { withFileTypes: true })
      .filter(entry => entry.isFile() && entry.name.endsWith('.json'))
      .map(entry => path.join(canonical, entry.name)),
  ]
  for (const source of candidates) {
    let project: HomologyProject
    try { project = readProjectFile(source) } catch { continue }
    const destination = path.join(canonical, safeId(project.id), 'homology-project.json')
    if (!fs.existsSync(destination)) {
      writeJsonAtomic(destination, project)
      continue
    }
    let same = false
    try { same = isDeepStrictEqual(readProjectFile(destination, project.id), project) } catch { /* preserve both */ }
    if (same) continue
    const digest = crypto.createHash('sha256').update(fs.readFileSync(source)).digest('hex').slice(0, 12)
    const conflict = path.join(canonical, '.migration-conflicts', `${project.id}-${digest}.json`)
    if (!fs.existsSync(conflict)) writeJsonAtomic(conflict, project)
  }
  return canonical
}

function projectRoot(root: string): string {
  return ensureHomologyStorage(root)
}

function projectPath(root: string, id: string): string {
  return path.join(projectRoot(root), safeId(id), 'homology-project.json')
}

export function saveHomologyProject(root: string, project: HomologyProject): HomologyProject {
  normalizedProject(project, project.id)
  const file = projectPath(root, project.id)
  fs.mkdirSync(path.dirname(file), { recursive: true })
  const next = { ...project, version: 1 as const, updatedAt: new Date().toISOString() }
  const existingBytes = fs.existsSync(file) ? fs.lstatSync(file).size : 0
  const nextBytes = Buffer.byteLength(`${JSON.stringify(next, null, 2)}\n`)
  assertWorkspaceQuota(root, Math.max(0, nextBytes - existingBytes))
  writeJsonAtomic(file, next)
  return next
}

export function loadHomologyProject(root: string, id: string): HomologyProject {
  const file = projectPath(root, id)
  if (!fs.existsSync(file)) throw new Error(`project not found: ${id}`)
  return readProjectFile(file, id)
}

export function parseFasta(text: string): Array<{ id: string; sequence: string }> {
  const records: Array<{ id: string; sequence: string }> = []
  let current: { id: string; sequence: string } | null = null
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim()
    if (!line) continue
    if (line.startsWith('>')) {
      if (current) records.push(current)
      const id = line.slice(1).trim().split(/\s+/)[0]
      if (!id) throw new Error('target FASTA header is empty')
      current = { id, sequence: '' }
    } else {
      if (!current) throw new Error('target sequence appears before a FASTA header')
      current.sequence += line.replace(/\s+/g, '').toUpperCase()
    }
  }
  if (current) records.push(current)
  if (!records.length) throw new Error('target FASTA is empty')
  if (new Set(records.map(record => record.id)).size !== records.length) throw new Error('target chain IDs must be unique')
  for (const record of records) {
    if (!record.sequence || /[^A-Z*?-]/.test(record.sequence)) throw new Error(`invalid target sequence: ${record.id}`)
  }
  return records
}

function parseAlignedFasta(file: string): Array<{ id: string; sequence: string }> {
  return parseFasta(fs.readFileSync(file, 'utf8'))
}

export function parseSequenceArtifact(file: string): Array<{ id: string; sequence: string; length: number }> {
  const extension = path.extname(file).toLowerCase()
  const text = fs.readFileSync(file, 'utf8')
  if (['.fasta', '.fa', '.faa', '.aln', '.txt'].includes(extension) || text.trimStart().startsWith('>')) {
    if (/^>P1;/m.test(text)) {
      const records: Array<{ id: string; sequence: string; length: number }> = []
      const chunks = text.split(/^>P1;/m).slice(1)
      for (const chunk of chunks) {
        const lines = chunk.split(/\r?\n/)
        const id = (lines.shift() || '').trim()
        lines.shift()
        const sequence = lines.join('').replace(/[\s*/]/g, '').toUpperCase()
        if (id && sequence) records.push({ id, sequence, length: sequence.length })
      }
      if (records.length) return records
    }
    return parseFasta(text).map(record => ({ ...record, length: record.sequence.replace(/[-*]/g, '').length }))
  }
  if (extension === '.pdb') {
    const seqres = new Map<string, string[]>()
    const seqresOrder: string[] = []
    for (const line of text.split(/\r?\n/)) {
      if (!line.startsWith('SEQRES')) continue
      const chain = (line[11] || ' ').trim() || '_'
      if (!seqres.has(chain)) { seqres.set(chain, []); seqresOrder.push(chain) }
      for (const residue of line.slice(19).trim().split(/\s+/)) {
        const aa = AA3[residue.toUpperCase()]
        if (aa) seqres.get(chain)!.push(aa)
      }
    }
    const seqresRecords = seqresOrder.map(id => ({ id, sequence: seqres.get(id)!.join(''), length: seqres.get(id)!.length })).filter(record => record.length)
    if (seqresRecords.length) return seqresRecords
    const chainOrder: string[] = []
    const residues = new Map<string, Map<string, string>>()
    for (const line of text.split(/\r?\n/)) {
      if (!line.startsWith('ATOM  ') && !line.startsWith('HETATM')) continue
      const aa = AA3[line.slice(17, 20).trim().toUpperCase()]
      if (!aa) continue
      const chain = (line[21] || ' ').trim() || '_'
      if (!residues.has(chain)) { residues.set(chain, new Map()); chainOrder.push(chain) }
      residues.get(chain)!.set(line.slice(22, 27).trim(), aa)
    }
    const records = chainOrder.map(id => ({ id, sequence: [...residues.get(id)!.values()].join(''), length: residues.get(id)!.size }))
    if (records.length) return records
  }
  if (extension === '.cif' || extension === '.mmcif') {
    const tokens = text.match(/'(?:[^']|'')*'|"(?:[^"]|"")*"|[^\s]+/g)?.map(token => token.replace(/^(['"])(.*)\1$/, '$2')) || []
    for (let index = 0; index < tokens.length; index++) {
      if (tokens[index] !== 'loop_') continue
      const headers: string[] = []
      while (tokens[index + 1]?.startsWith('_')) headers.push(tokens[++index])
      if (!headers.includes('_atom_site.group_PDB')) continue
      const groupAt = headers.indexOf('_atom_site.group_PDB')
      const chainAt = headers.indexOf('_atom_site.auth_asym_id') >= 0 ? headers.indexOf('_atom_site.auth_asym_id') : headers.indexOf('_atom_site.label_asym_id')
      const seqAt = headers.indexOf('_atom_site.auth_seq_id') >= 0 ? headers.indexOf('_atom_site.auth_seq_id') : headers.indexOf('_atom_site.label_seq_id')
      const compAt = headers.indexOf('_atom_site.auth_comp_id') >= 0 ? headers.indexOf('_atom_site.auth_comp_id') : headers.indexOf('_atom_site.label_comp_id')
      if (chainAt < 0 || seqAt < 0 || compAt < 0) break
      const rows = new Map<string, Map<string, string>>()
      const order: string[] = []
      while (index + headers.length < tokens.length) {
        const row = tokens.slice(index + 1, index + 1 + headers.length)
        if (row[0] === 'loop_' || row[0] === 'stop_' || row[0]?.startsWith('_') || row[0]?.startsWith('data_')) break
        index += headers.length
        if (row[groupAt] !== 'ATOM' && row[groupAt] !== 'HETATM') continue
        const aa = AA3[row[compAt]?.toUpperCase()]
        if (!aa) continue
        const chain = row[chainAt] === '.' || row[chainAt] === '?' ? '_' : row[chainAt]
        if (!rows.has(chain)) { rows.set(chain, new Map()); order.push(chain) }
        rows.get(chain)!.set(row[seqAt], aa)
      }
      const records = order.map(id => ({ id, sequence: [...rows.get(id)!.values()].join(''), length: rows.get(id)!.size }))
      if (records.length) return records
    }
  }
  throw new Error(`sequence parsing is not supported for ${path.basename(file)}`)
}

function listFiles(directory: string): string[] {
  const output: string[] = []
  const walk = (current: string) => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.isFile()) output.push(full)
    }
  }
  walk(directory)
  return output
}

async function alignProject(
  root: string,
  project: HomologyProject,
  authorizePublication: () => void = () => {},
  signal?: AbortSignal,
): Promise<HomologyProject> {
  const records = parseFasta(project.targetFasta)
  const directory = path.dirname(projectPath(root, project.id))
  const groups: AlignmentGroup[] = []
  for (const record of records) {
    const templates = project.templates.filter(template => template.targetChain === record.id)
    if (!templates.length) throw new Error(`target chain ${record.id} has no assigned template`)
    const input = path.join(directory, `_target_${record.id}.fasta`)
    const output = path.join(directory, `_alignment_${record.id}.fasta`)
    fs.writeFileSync(input, `>${record.id}\n${record.sequence}\n`)
    const args = [input, '-o', output, '--engine', project.engine]
    for (const template of templates) {
      // MSA correspondence must always come from the user's source template.
      // Per-chain fitted artifacts can live in different reference frames and
      // are for inspection/export only, never for rebuilding model inputs.
      const source = resolveArtifact(root, template.file)
      args.push('--template', `${source}:${template.chain}`)
    }
    const result = await runDvbfixerArgs('msa', args, directory, { signal })
    assertRunAdmitted(result)
    if (result.code !== 0) throw new Error(result.stderr || result.stdout || `MSA failed for ${record.id}`)
    const aligned = parseAlignedFasta(output)
    const rows: AlignmentRow[] = aligned.map(row => {
      if (row.id === record.id) return { ...row, kind: 'target' as const }
      const match = /^template_(\d+)_/.exec(row.id)
      const index = match ? Number(match[1]) - 1 : -1
      const template = templates[index]
      if (!template) throw new Error(`cannot map aligned template row ${row.id}`)
      return { ...row, id: template.id, kind: 'template' as const, templateId: template.id }
    })
    groups.push({ chainId: record.id, rows, masks: {}, maskModes: Object.fromEntries(rows.filter(row => row.kind === 'template').map(row => [row.id, 'all'])) })
  }
  authorizePublication()
  return saveHomologyProject(root, { ...project, alignmentGroups: groups })
}

interface PdbResidue { key: string; chain: string; number: string; aa: string; lines: string[] }

function pdbResidues(file: string, chain: string): PdbResidue[] {
  const residues: PdbResidue[] = []
  const byKey = new Map<string, PdbResidue>()
  for (const line of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    if (!line.startsWith('ATOM  ') && !line.startsWith('HETATM')) continue
    if ((line[21] || ' ').trim() !== chain) continue
    const residueName = line.slice(17, 20).trim().toUpperCase()
    const aa = AA3[residueName]
    if (!aa) continue
    const number = line.slice(22, 27).trim()
    const key = `${chain}:${number}`
    let residue = byKey.get(key)
    if (!residue) {
      residue = { key, chain, number, aa, lines: [] }
      byKey.set(key, residue)
      residues.push(residue)
    }
    residue.lines.push(`${line}\n`)
  }
  if (!residues.length) throw new Error(`no protein residues found for chain ${chain} in ${file}`)
  return residues
}

function sanitize(value: string): string {
  return value.replace(/[^a-zA-Z0-9_-]+/g, '_')
}

export function materializeModelInputs(root: string, project: HomologyProject, runDir: string): {
  fasta: string; pir: string; fragments: string[]
} {
  if (!project.alignmentGroups.length) throw new Error('generate an alignment before modeling')
  for (const group of project.alignmentGroups) {
    if (new Set(group.rows.map(row => row.sequence.length)).size !== 1) {
      throw new Error(`alignment rows for target chain ${group.chainId} have different lengths`)
    }
  }
  const targetRecords = parseFasta(project.targetFasta)
  const groupLengths = project.alignmentGroups.map(group => group.rows[0]?.sequence.length || 0)
  if (groupLengths.some(length => length === 0)) throw new Error('alignment contains an empty chain group')
  const fasta = path.join(runDir, 'target.fasta')
  fs.writeFileSync(fasta, targetRecords.map(record => `>${record.id}\n${record.sequence.replace(/[-*]/g, '')}\n`).join(''))

  const compositeBlocks: string[] = []
  const compositeLines: string[] = []
  let atomSerial = 1
  let firstPosition: { number: number; chain: string } | null = null
  let lastPosition: { number: number; chain: string } | null = null
  for (let groupIndex = 0; groupIndex < project.alignmentGroups.length; groupIndex++) {
    const group = project.alignmentGroups[groupIndex]
    const targetRow = group.rows.find(item => item.kind === 'target')
    if (!targetRow) throw new Error(`target row missing for chain ${group.chainId}`)
    const chosen: Array<PdbResidue | null> = Array(groupLengths[groupIndex]).fill(null)
    for (const row of group.rows.filter(item => item.kind === 'template')) {
      const template = project.templates.find(item => item.id === row.templateId)
      if (!template) throw new Error(`template metadata missing for ${row.id}`)
      const source = resolveArtifact(root, template.fittedFile || template.file)
      const residues = pdbResidues(source, template.chain)
      const alignedSequence = row.sequence.replace(/-/g, '')
      const coordinateSequence = residues.map(residue => residue.aa).join('')
      if (alignedSequence !== coordinateSequence) {
        let mismatch = 0
        while (mismatch < Math.min(alignedSequence.length, coordinateSequence.length) &&
               alignedSequence[mismatch] === coordinateSequence[mismatch]) mismatch++
        throw new Error(
          `alignment row ${row.id} is not mapped to ${template.file}:${template.chain} ` +
          `(first difference at residue ${mismatch + 1}); regenerate the alignment`,
        )
      }
      const rowResidueByColumn: Array<PdbResidue | null> = []
      let residueIndex = 0
      for (const character of row.sequence) {
        rowResidueByColumn.push(character === '-' ? null : (residues[residueIndex++] || null))
      }
      if (residueIndex !== residues.length) {
        throw new Error(`alignment row ${row.id} does not match ${template.file}:${template.chain}`)
      }
      const mode = group.maskModes?.[row.id] || (group.masks[row.id]?.length ? 'ranges' : 'all')
      const spans = mode === 'none' ? [] : mode === 'ranges' ? (group.masks[row.id] || []) : [{ start: 0, end: row.sequence.length }]
      for (const span of spans) {
        for (let column = Math.max(0, span.start); column < Math.min(span.end, chosen.length); column++) {
          // Template insertions have no target residue to receive them. When
          // masks overlap, earlier template rows have explicit precedence.
          if (targetRow.sequence[column] !== '-' && !chosen[column] && rowResidueByColumn[column]) {
            chosen[column] = rowResidueByColumn[column]
          }
        }
      }
    }
    let targetOrdinal = 0
    const block: string[] = []
    for (let column = 0; column < targetRow.sequence.length; column++) {
      if (targetRow.sequence[column] !== '-') targetOrdinal++
      const residue = chosen[column]
      block.push(residue ? residue.aa : '-')
      if (!residue) continue
      firstPosition ||= { number: targetOrdinal, chain: group.chainId }
      lastPosition = { number: targetOrdinal, chain: group.chainId }
      for (const raw of residue.lines) {
        const line = raw.replace(/\r?\n$/, '').padEnd(80, ' ')
        compositeLines.push(
          `${line.slice(0, 6)}${String(atomSerial++).padStart(5)}${line.slice(11, 21)}` +
          `${group.chainId.slice(0, 1) || ' '}${String(targetOrdinal).padStart(4)} ${line.slice(27)}\n`,
        )
      }
    }
    compositeBlocks.push(block.join(''))
    compositeLines.push('TER\n')
  }
  if (!firstPosition || !lastPosition) throw new Error('template masks select no residues')
  const compositeCode = 'selected_template_mosaic'
  const composite = path.join(runDir, `${compositeCode}.pdb`)
  fs.writeFileSync(composite, `${compositeLines.join('')}END\n`)
  const fragments = [composite]
  const targetBlocks = project.alignmentGroups.map(group => {
    const row = group.rows.find(item => item.kind === 'target')
    if (!row) throw new Error(`target row missing for chain ${group.chainId}`)
    return row.sequence
  })
  const pir = path.join(runDir, 'alignment.pir')
  fs.writeFileSync(pir,
    `>P1;${compositeCode}\nstructureX:${compositeCode}:${firstPosition.number}:${firstPosition.chain}:` +
    `${lastPosition.number}:${lastPosition.chain}::::\n${compositeBlocks.join('/')}*\n` +
    `>P1;target\nsequence:target::::::::\n${targetBlocks.join('/')}*\n`)
  return { fasta, pir, fragments }
}

function registerRun(
  root: string,
  project: HomologyProject,
  files: string[],
  authorizePublication: () => void,
  diffusion?: ReturnType<typeof readDiffusionPublication>,
): string {
  const relativeFiles = files.map(file => path.relative(root, file).replace(/\\/g, '/'))
  const primary = diffusion ? (diffusion.primary ? path.relative(root, diffusion.primary).replace(/\\/g, '/') : null)
    : relativeFiles.find(file => file.endsWith('.pdb')) || relativeFiles[0]
  if (relativeFiles.length === 0) return ''
  const dataRoot = path.dirname(path.dirname(root))
  const workspaceId = path.basename(root)
  updateWorkspace(dataRoot, workspaceId, manifest => {
    authorizePublication()
    for (const relative of relativeFiles) {
      if (manifest.artifacts.some(artifact => artifact.file === relative)) continue
      manifest.artifacts.push({
        id: crypto.randomUUID(), file: relative,
        name: relative === primary ? `${project.name} → homology`
          : `${diffusion?.status === 'validation_failed' && relative.endsWith('.pdb') ? '[rejected] ' : ''}${path.basename(relative)}`,
        kind: relative.endsWith('.pdb') ? 'structure' : 'artifact', artifactType: 'homology-model',
        command: 'homology', folder: path.dirname(relative),
        hidden: ['run.json', 'stdout.log', 'stderr.log', 'target.fasta', 'alignment.pir'].includes(path.basename(relative)) ||
          path.basename(relative).startsWith('_') || (relative.endsWith('.pdb') && relative !== primary &&
            !(diffusion?.candidates.includes(path.join(root, relative))) && !path.basename(relative).startsWith(sanitize(project.name || 'target'))),
      })
    }
    manifest.toolState = { ...manifest.toolState, lastHomologyRun: { projectId: project.id, files: relativeFiles } }
    return manifest
  })
  return primary || ''
}

async function modelProject(
  root: string,
  project: HomologyProject,
  authorizePublication: () => void = () => {},
  signal?: AbortSignal,
): Promise<unknown> {
  const runDir = path.join(root, 'runs', `dvb_homology_${new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)}`)
  fs.mkdirSync(runDir, { recursive: true })
  const fasta = path.join(runDir, 'target.fasta')
  fs.writeFileSync(fasta, parseFasta(project.targetFasta).map(record => `>${record.id}\n${record.sequence.replace(/[-*]/g, '')}\n`).join(''))
  const plan = path.join(runDir, 'template-plan.json')
  writeJsonAtomic(plan, {
    templates: project.templates.map(template => ({
      id: template.id, path: resolveArtifact(root, template.file), chain: template.chain,
      targetChain: template.targetChain,
    })),
    alignmentGroups: project.alignmentGroups,
  })
  const nativeRoot = project.modelOptions['--backend'] === 'diffusion'
    ? fs.mkdtempSync(path.join(os.tmpdir(), 'dvbfixer-homology-')) : undefined
  const prefix = path.join(nativeRoot || runDir, sanitize(project.name || 'target'))
  const args = [fasta, '--template-plan', plan, '-o', prefix]
  args.push(...validatedModelArgs(project.modelOptions))
  if (nativeRoot) args.push('--diffusion-work-parent', nativeRoot)
  try {
  const result = await runDvbfixerArgs('homology', args, runDir, { signal })
  assertRunAdmitted(result)
  writeJsonAtomic(path.join(runDir, 'run.json'), { projectId: project.id, args, exitCode: result.code })
  fs.writeFileSync(path.join(runDir, 'stdout.log'), result.stdout)
  fs.writeFileSync(path.join(runDir, 'stderr.log'), result.stderr)
  if (nativeRoot && result.code === 0 && !signal?.aborted) {
    authorizePublication()
    const indexes = listFiles(nativeRoot).filter(file => path.basename(file) === 'bundle.json')
    if (indexes.length !== 1) throw new Error('homology diffusion did not publish exactly one complete bundle')
    for (const index of indexes) readDiffusionPublication(index)
    for (const entry of fs.readdirSync(nativeRoot)) {
      fs.cpSync(path.join(nativeRoot, entry), path.join(runDir, entry), { recursive: true, force: false, errorOnExist: true })
    }
  }
  const files = listFiles(runDir)
  const bundleManifest = files.find(file => path.basename(file) === 'bundle.json')
  let modelStatus = result.code === 0 ? 'success' : 'failed'
  let diffusion: ReturnType<typeof readDiffusionPublication> | undefined
  if (bundleManifest) {
    diffusion = readDiffusionPublication(bundleManifest)
    modelStatus = diffusion.status
  }
  const outputFile = result.code === 0 ? registerRun(root, project, files, authorizePublication, diffusion) : ''
  return { ok: result.code === 0, exitCode: result.code, stdout: result.stdout, stderr: result.stderr,
    modelStatus,
    outputFile, outputDir: path.relative(root, runDir).replace(/\\/g, '/'),
    artifacts: files.map(file => path.relative(root, file).replace(/\\/g, '/')) }
  } finally {
    if (nativeRoot) fs.rmSync(nativeRoot, { recursive: true, force: true })
  }
}

async function structurallyAlignGroups(
  root: string,
  project: HomologyProject,
  authorizePublication: () => void = () => {},
  signal?: AbortSignal,
): Promise<HomologyProject> {
  const directory = path.dirname(projectPath(root, project.id))
  const templates: TemplateSelection[] = project.templates.map(template => ({ ...template, fittedFile: undefined }))
  const outputs: Record<string, string> = {}
  const targetChains = [...new Set(templates.map(template => template.targetChain))]
  const globalReferenceFile = templates[0]?.file
  for (const targetChain of targetChains) {
    const members = templates.filter(template => template.targetChain === targetChain)
    const sharedReference = members.find(template => template.file === globalReferenceFile)
    if (targetChains.length > 1 && !sharedReference) {
      throw new Error(
        `target chain ${targetChain} has no template from the common reference structure ${globalReferenceFile}; ` +
        'add that structure/chain to every target-chain group so fitted coordinates share one frame',
      )
    }
    const group = sharedReference
      ? [sharedReference, ...members.filter(template => template.id !== sharedReference.id)]
      : members
    if (group.length < 2) continue
    const safeChain = sanitize(targetChain)
    const output = path.join(directory, `structural_alignment_${safeChain}.pir`)
    const fitDir = path.join(directory, 'fitted', safeChain)
    const args = group.map(template => `${resolveArtifact(root, template.file)}:${template.chain}`)
    args.push('-o', output, '--fit-dir', fitDir, '--engine', 'biopython')
    const result = await runDvbfixerArgs('salign', args, directory, { signal })
    assertRunAdmitted(result)
    if (result.code !== 0) throw new Error(result.stderr || result.stdout || `structural alignment failed for target chain ${targetChain}`)
    outputs[targetChain] = path.relative(root, output).replace(/\\/g, '/')
    group.forEach((template, index) => {
      const candidate = path.join(fitDir, `template_${index + 1}_${template.chain || 'all'}_fit.pdb`)
      if (!fs.existsSync(candidate)) throw new Error(`structural fitting did not produce ${path.basename(candidate)}`)
      template.fittedFile = path.relative(root, candidate).replace(/\\/g, '/')
    })
  }
  authorizePublication()
  return saveHomologyProject(root, { ...project, templates, structuralAlignment: outputs })
}

export function registerHomologyApi(
  server: ApiRouteHost,
  root: string,
  principalSource: (request: IncomingMessage) => string = () => 'local',
  legacyOwnerPrincipalId = 'local',
): void {
  server.middlewares.use('/api/homology', async (req, res, next) => {
    try {
      const controller = new AbortController()
      res.once('close', () => { if (!res.writableFinished) controller.abort() })
      const principalId = principalSource(req)
      const authorize = (workspaceId: string, access: 'reader' | 'writer' = 'reader') => {
        const workspace = loadWorkspace(root, workspaceId, legacyOwnerPrincipalId)
        assertWorkspaceAccess(workspace, principalId, access)
        const storageRoot = workspaceRoot(root, workspaceId)
        if (access === 'writer') assertWorkspaceQuota(storageRoot)
        return storageRoot
      }
      const publicationGuard = (workspaceId: string) => () => {
        const storageRoot = authorize(workspaceId, 'writer')
        assertWorkspaceQuota(storageRoot)
      }
      const requestUrl = new URL(req.url || '/', 'http://localhost')
      const parts = requestUrl.pathname.split('/').filter(Boolean)
      const queryWorkspace = requestUrl.searchParams.get('workspaceId') || ''
      if (req.method === 'GET' && parts[0] === 'projects' && !parts[1]) {
        if (!queryWorkspace) return sendJson(res, 400, { error: 'workspaceId is required' })
        const storageRoot = authorize(queryWorkspace)
        const projects = fs.readdirSync(projectRoot(storageRoot), { withFileTypes: true })
          .filter(entry => entry.isDirectory())
          .flatMap(entry => {
            try { return [loadHomologyProject(storageRoot, entry.name)] } catch { return [] }
          })
          .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
          .map(project => ({ id: project.id, name: project.name, updatedAt: project.updatedAt }))
        return sendJson(res, 200, projects)
      }
      if (req.method === 'GET' && parts[0] === 'engines') {
        const result = await runDvbfixerArgs('msa', ['--list-engines'], process.cwd(), { signal: controller.signal })
        assertRunAdmitted(result)
        const engines = Object.fromEntries(result.stdout.trim().split(/\r?\n/).filter(Boolean).map(line => {
          const [name, ...rest] = line.split(':')
          const executable = rest.join(':').trim()
          return [name, { available: executable !== 'MISSING', path: executable === 'MISSING' ? null : executable }]
        }))
        return sendJson(res, result.code === 0 ? 200 : 500, engines)
      }
      if (req.method === 'POST' && (parts[0] === 'parse-sequence' || parts[0] === 'chains')) {
        const body = JSON.parse(await readBody(req) || '{}') as { workspaceId?: string; file?: string }
        if (!body.workspaceId || !body.file) return sendJson(res, 400, { error: 'workspaceId and file are required' })
        const file = resolveArtifact(authorize(body.workspaceId), body.file)
        const records = parseSequenceArtifact(file)
        return sendJson(res, 200, parts[0] === 'chains'
          ? records.map(record => ({ id: record.id, length: record.length, sequence: record.sequence }))
          : { records })
      }
      if (req.method === 'POST' && parts[0] === 'projects' && !parts[1]) {
        const request = JSON.parse(await readBody(req) || '{}') as { workspaceId?: string }
        if (!request.workspaceId) return sendJson(res, 400, { error: 'workspaceId is required' })
        const storageRoot = authorize(request.workspaceId, 'writer')
        const now = new Date().toISOString()
        const project: HomologyProject = {
          version: 1, id: crypto.randomUUID(), name: 'Untitled homology project', targetFasta: '',
          templates: [], engine: 'mafft', alignmentGroups: [], modelOptions: {
            '--num-models': 5, '--md-level': 'fast',
          }, createdAt: now, updatedAt: now,
        }
        return sendJson(res, 201, saveHomologyProject(storageRoot, project))
      }
      if (parts[0] === 'projects' && parts[1] && req.method === 'GET') {
        if (!queryWorkspace) return sendJson(res, 400, { error: 'workspaceId is required' })
        return sendJson(res, 200, loadHomologyProject(authorize(queryWorkspace), parts[1]))
      }
      if (parts[0] === 'projects' && parts[1] && req.method === 'PUT') {
        const incoming = JSON.parse(await readBody(req)) as HomologyProject
        const workspaceId = (incoming as any).workspaceId as string
        if (!workspaceId) return sendJson(res, 400, { error: 'workspaceId is required' })
        const storageRoot = authorize(workspaceId, 'writer')
        const current = loadHomologyProject(storageRoot, parts[1])
        const { workspaceId: _workspaceId, ...clean } = incoming as any
        void _workspaceId
        return sendJson(res, 200, saveHomologyProject(storageRoot, { ...clean, id: current.id, createdAt: current.createdAt, version: 1 }))
      }
      if (req.method === 'POST' && parts[0] === 'align') {
        const incoming = JSON.parse(await readBody(req)) as HomologyProject & { workspaceId?: string }
        if (!incoming.workspaceId) return sendJson(res, 400, { error: 'workspaceId is required' })
        const { workspaceId, ...project } = incoming
        return sendJson(res, 200, await alignProject(
          authorize(workspaceId, 'writer'), project, publicationGuard(workspaceId), controller.signal,
        ))
      }
      if (req.method === 'POST' && parts[0] === 'salign') {
        const incoming = JSON.parse(await readBody(req)) as HomologyProject & { workspaceId?: string }
        if (!incoming.workspaceId) return sendJson(res, 400, { error: 'workspaceId is required' })
        const { workspaceId, ...project } = incoming
        const storageRoot = authorize(workspaceId, 'writer')
        if (project.templates.length < 2) return sendJson(res, 400, { error: 'select at least two templates' })
        return sendJson(res, 200, await structurallyAlignGroups(
          storageRoot, project, publicationGuard(workspaceId), controller.signal,
        ))
      }
      if (req.method === 'POST' && parts[0] === 'model') {
        const incoming = JSON.parse(await readBody(req)) as HomologyProject & { workspaceId?: string }
        if (!incoming.workspaceId) return sendJson(res, 400, { error: 'workspaceId is required' })
        const { workspaceId, ...project } = incoming
        const storageRoot = authorize(workspaceId, 'writer')
        const result = await modelProject(
          storageRoot, project, publicationGuard(workspaceId), controller.signal,
        ) as { ok: boolean }
        return sendJson(res, result.ok ? 200 : 500, result)
      }
      return next()
    } catch (error: any) {
      return sendJson(res, errorStatus(error), { error: error?.message || String(error) })
    }
  })
}
