import { renderToStaticMarkup } from 'react-dom/server'
import { ThemeProvider } from '@mui/material/styles'
import { describe, expect, it } from 'vitest'
import { theme } from '../theme'
import { ArtifactFileIdentity } from './ArtifactFileIdentity'

describe('workspace file identity presentation', () => {
  it('shows an accessible category icon and exact format even when the display name has no extension', () => {
    const markup = renderToStaticMarkup(<ThemeProvider theme={theme}>
      <ArtifactFileIdentity artifact={{ id: 'a', file: 'runs/result.pdb', name: 'Prepared antibody', kind: 'structure' }} />
    </ThemeProvider>)
    expect(markup).toContain('Prepared antibody')
    expect(markup).toContain('aria-label="Structure"')
    expect(markup).toContain('BiotechIcon')
    expect(markup).toContain('>PDB<')
    expect(markup).toContain('height:24px')
    expect(markup).toContain('text-overflow:ellipsis')
  })

  it('ignores misleading user display extensions and keeps reports visually distinct', () => {
    const markup = renderToStaticMarkup(<ArtifactFileIdentity artifact={{
      id: 'a', file: 'runs/diagnose.json', name: 'My file.pdb', kind: 'artifact', artifactType: 'report',
    }} />)
    expect(markup).toContain('My file.pdb')
    expect(markup).toContain('aria-label="Report"')
    expect(markup).toContain('AssessmentIcon')
    expect(markup).toContain('>JSON<')
    expect(markup).not.toContain('>PDB<')
  })
})
