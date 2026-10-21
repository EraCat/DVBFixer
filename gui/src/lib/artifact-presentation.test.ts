import { describe, expect, it } from 'vitest'
import { artifactPresentation, visibleWorkspaceArtifacts } from './artifact-presentation'
import { reorderVisibleArtifacts } from './workspace-order'

describe('workspace file identity', () => {
  it.each([
    ['inputs/structure.PDB', 'structure', 'PDB'],
    ['inputs/structure.mmcif', 'structure', 'MMCIF'],
    ['inputs/structure.pdb.gz', 'structure', 'PDB.GZ'],
    ['inputs/target.fasta', 'sequence', 'FASTA'],
    ['inputs/target.aln', 'alignment', 'ALN'],
    ['runs/table.csv', 'table', 'CSV'],
    ['runs/stdout.log', 'log', 'LOG'],
    ['inputs/settings.yaml', 'settings', 'YAML'],
    ['inputs/data.json', 'data', 'JSON'],
    ['inputs/README', 'other', 'FILE'],
    ['inputs/README.gz', 'other', 'GZ'],
    ['inputs/.hidden', 'other', 'FILE'],
    ['inputs/file.unknown', 'other', 'UNKNOWN'],
  ])('classifies %s from its real path', (file, category, format) => {
    expect(artifactPresentation({ file, kind: 'artifact' })).toMatchObject({ category, format })
  })

  it('distinguishes reports and settings with the same JSON format', () => {
    const report = artifactPresentation({ file: 'report.json', kind: 'artifact', artifactType: 'report', command: 'diagnose' })
    const settings = artifactPresentation({ file: 'settings.json', kind: 'artifact', artifactType: 'config' })
    expect(report).toMatchObject({ category: 'report', format: 'JSON' })
    expect(settings).toMatchObject({ category: 'settings', format: 'JSON' })
    expect(report.tooltip).toContain('Created by: diagnose')
    expect(settings.tooltip).toContain('Origin: not recorded')
  })

  it('preserves authoritative structure metadata and full case-sensitive paths', () => {
    const presentation = artifactPresentation({ file: 'Inputs/ChainD.bin', kind: 'structure', command: 'prepare' })
    expect(presentation.category).toBe('structure')
    expect(presentation.tooltip).toContain('Path: Inputs/ChainD.bin')
    expect(presentation.tooltip).toContain('Created by: prepare')
  })
})

describe('structure-only workspace filter', () => {
  const artifacts = [
    { id: 'pdb', file: 'a.pdb', kind: 'structure' as const },
    { id: 'report', file: 'report.json', kind: 'artifact' as const },
    { id: 'cif', file: 'b.CIF', kind: 'artifact' as const },
    { id: 'mmcif', file: 'c.mmcif', kind: 'structure' as const },
    { id: 'sequence', file: 'target.fasta', kind: 'artifact' as const },
    { id: 'ent', file: 'd.ent', kind: 'structure' as const },
    { id: 'compressed', file: 'e.cif.gz', kind: 'artifact' as const },
    { id: 'hidden', file: 'hidden.pdb', kind: 'structure' as const, hidden: true },
  ]

  it('keeps CIF/mmCIF and other recognized structures, not just PDB', () => {
    expect(visibleWorkspaceArtifacts(artifacts, true).map(item => item.id))
      .toEqual(['pdb', 'cif', 'mmcif', 'ent', 'compressed'])
  })

  it('restores non-structure files in original order without showing hidden artifacts', () => {
    expect(visibleWorkspaceArtifacts(artifacts, false)).toEqual(artifacts.slice(0, -1))
  })

  it('reorders the same visible structure rows without moving hidden file slots', () => {
    const visible = visibleWorkspaceArtifacts(artifacts, true)
    const reordered = reorderVisibleArtifacts(artifacts, visible.map(item => item.id), new Set(['cif']), -1)
    expect(reordered.map(item => item.id))
      .toEqual(['cif', 'report', 'pdb', 'mmcif', 'sequence', 'ent', 'compressed', 'hidden'])
    expect(artifacts[0].id).toBe('pdb')
  })
})
