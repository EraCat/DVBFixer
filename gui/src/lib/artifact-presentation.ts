import type { WorkspaceArtifact } from '../stores/workspaceStore'

export type ArtifactCategory = 'structure' | 'sequence' | 'alignment' | 'table' | 'report' | 'log' | 'settings' | 'data' | 'other'
type ArtifactIdentity = Pick<WorkspaceArtifact, 'file' | 'kind' | 'artifactType' | 'command' | 'namingProvenance'>

const LABELS: Record<ArtifactCategory, string> = {
  structure: 'Structure', sequence: 'Sequence', alignment: 'Alignment', table: 'Table',
  report: 'Report', log: 'Log', settings: 'Settings', data: 'Data', other: 'File',
}

/** Presentation only: never infer file type from the user-editable display name. */
export function artifactPresentation(artifact: ArtifactIdentity) {
  const basename = artifact.file.split(/[\\/]/).pop() || ''
  const compressed = /\.(gz|bz2|xz)$/i.test(basename)
  const contentName = compressed ? basename.replace(/\.(gz|bz2|xz)$/i, '') : basename
  const extension = /[^.]\.([^.]+)$/.exec(contentName)?.[1]?.toLowerCase() || ''
  const compression = compressed ? basename.split('.').pop()?.toUpperCase() : ''
  const format = extension ? `${extension.toUpperCase()}${compression ? `.${compression}` : ''}` : compression || 'FILE'
  const type = artifact.artifactType?.toLowerCase()
  let category: ArtifactCategory = 'other'
  if (type === 'report') category = 'report'
  else if (type === 'log' || extension === 'log') category = 'log'
  else if (type === 'settings' || type === 'config') category = 'settings'
  else if (artifact.kind === 'structure' || /^(pdb|ent|cif|mmcif|bcif|gro|mol2|sdf)$/.test(extension)) category = 'structure'
  else if (/^(fasta|fa|faa|fna|ffn|frn|pir)$/.test(extension)) category = 'sequence'
  else if (/^(aln|sto|stockholm|a2m|a3m)$/.test(extension)) category = 'alignment'
  else if (/^(csv|tsv|xlsx|xls)$/.test(extension)) category = 'table'
  else if (/^(yaml|yml|toml|ini|cfg)$/.test(extension)) category = 'settings'
  else if (/^(json|xml|dat|top|itp|mdp)$/.test(extension)) category = 'data'
  const label = LABELS[category]
  const command = artifact.command || artifact.namingProvenance?.command
  const tooltip = [
    `${label} · ${format}`, `Path: ${artifact.file}`,
    command ? `Created by: ${command}` : 'Origin: not recorded',
    artifact.namingProvenance?.sourceFile ? `Source: ${artifact.namingProvenance.sourceFile}` : '',
  ].filter(Boolean).join('\n')
  return { category, label, format, tooltip }
}
