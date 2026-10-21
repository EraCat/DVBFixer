import { describe, expect, it } from 'vitest'
import { artifactPresentation } from './artifact-presentation'

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
