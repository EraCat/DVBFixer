export const PANEL_DEFINITIONS = [
  { component: 'viewer', name: '3D Structure' },
  { component: 'viewer2', name: '3D Structure (B)' },
  { component: 'sequence', name: 'Sequence' },
  { component: 'elements', name: 'Elements' },
  { component: 'interactions', name: 'Interactions' },
  { component: 'clashes', name: 'Clashes' },
  { component: 'alignment', name: 'Alignment' },
  { component: 'dvbfixer', name: 'DVBFixer' },
  { component: 'homology', name: 'Homology' },
  { component: 'text-viewer', name: 'Text Files' },
  { component: 'library', name: 'Library' },
  { component: 'workspace', name: 'Workspace' },
  { component: 'info', name: 'Info' },
  { component: 'settings', name: 'Settings' },
] as const

export const DEFAULT_MAIN_PANELS = PANEL_DEFINITIONS.filter(({ component }) =>
  component === 'viewer' || component === 'dvbfixer' || component === 'homology' || component === 'text-viewer')
