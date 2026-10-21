import { describe, expect, it } from 'vitest'
import { DEFAULT_MAIN_PANELS, PANEL_DEFINITIONS } from './app-panels'

describe('application panel registry', () => {
  it('keeps retained structure workflows available and retires mutation-cluster panels', () => {
    const registered = PANEL_DEFINITIONS.map(panel => panel.component)
    expect(registered).toEqual(expect.arrayContaining([
      'viewer', 'dvbfixer', 'homology', 'library', 'workspace', 'alignment',
    ]))
    expect(registered).not.toEqual(expect.arrayContaining(['mutations', 'antibody-engineer']))
    expect(DEFAULT_MAIN_PANELS.map(panel => panel.component)).toEqual([
      'viewer', 'dvbfixer', 'homology', 'text-viewer',
    ])
  })
})
