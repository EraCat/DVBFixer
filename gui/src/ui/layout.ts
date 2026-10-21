/** Shared desktop control geometry. Keep docs/gui-design-system.md in sync. */
export const UI = {
  controlHeight: 32,
  compactHeight: 24,
  iconSize: 18,
  compactIconSize: 14,
  actionWidth: 160,
  fieldWidth: 160,
  wideFieldWidth: 320,
  toolbarMinHeight: 48,
} as const

export const toolbarSx = {
  display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1,
  px: 1.5, py: 1, minHeight: UI.toolbarMinHeight, boxSizing: 'border-box',
  flexShrink: 0, bgcolor: 'background.paper',
} as const

export const panelToolbarSx = {
  ...toolbarSx, borderBottom: 1, borderColor: 'divider',
} as const

export const actionGroupSx = {
  display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 1, ml: 'auto',
} as const

/** Use when fields have helper text below them; actions align to the input, not its caption. */
export const formActionRowSx = {
  display: 'flex', alignItems: 'flex-start', flexWrap: 'wrap', gap: 1,
} as const

export const controlSx = { width: UI.fieldWidth, minWidth: UI.fieldWidth, maxWidth: '100%' } as const
export const wideControlSx = { width: UI.wideFieldWidth, minWidth: 0, maxWidth: '100%' } as const
export const primaryActionSx = {
  width: UI.actionWidth, minWidth: UI.actionWidth, height: UI.controlHeight, flexShrink: 0,
} as const
export const controlWrapperSx = { display: 'inline-flex', alignItems: 'center' } as const
export const actionTooltipWrapperSx = { ...controlWrapperSx, ...primaryActionSx } as const

export const workflowToolbarSx = {
  ...toolbarSx,
  '& .MuiButton-root': primaryActionSx,
} as const

export const compactIconButtonSx = {
  width: UI.compactHeight, minWidth: UI.compactHeight, height: UI.compactHeight, minHeight: UI.compactHeight, p: 0.5,
  '& .MuiSvgIcon-root': { fontSize: UI.compactIconSize },
} as const

export const inlineActionSx = {
  height: UI.compactHeight, minHeight: UI.compactHeight, minWidth: 0, px: 1,
} as const
