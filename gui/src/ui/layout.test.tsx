import { renderToStaticMarkup } from 'react-dom/server'
import { ThemeProvider } from '@mui/material/styles'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import TextField from '@mui/material/TextField'
import Box from '@mui/material/Box'
import AddIcon from '@mui/icons-material/Add'
import { describe, expect, it } from 'vitest'
import { theme } from '../theme'
import { UI, actionGroupSx, compactIconButtonSx, formActionRowSx, panelToolbarSx, primaryActionSx, workflowToolbarSx } from './layout'

describe('shared GUI control geometry', () => {
  it('uses one height for buttons, icon buttons, toggles and input controls', () => {
    expect(theme.components?.MuiButton?.styleOverrides?.root).toMatchObject({ height: UI.controlHeight, minHeight: UI.controlHeight })
    expect(theme.components?.MuiIconButton?.styleOverrides?.root).toMatchObject({ width: UI.controlHeight, height: UI.controlHeight })
    expect(theme.components?.MuiToggleButton?.styleOverrides?.root).toMatchObject({ height: UI.controlHeight })
    expect(theme.components?.MuiOutlinedInput?.styleOverrides?.root).toMatchObject({ '&:not(.MuiInputBase-multiline)': { height: UI.controlHeight } })
    expect(theme.components?.MuiInputLabel?.styleOverrides?.sizeSmall).toMatchObject({
      transform: 'translate(14px, 6px) scale(1)',
      '&.MuiInputLabel-shrink': { transform: 'translate(14px, -8px) scale(0.75)' },
    })
  })

  it('keeps workflow actions 160×32 and dense row actions explicitly 24×24', () => {
    expect(primaryActionSx).toMatchObject({ width: 160, height: 32 })
    expect(workflowToolbarSx['& .MuiButton-root']).toBe(primaryActionSx)
    expect(compactIconButtonSx).toMatchObject({ width: 24, height: 24, minWidth: 24 })
  })

  it('wraps toolbars and action groups rather than shifting controls with transforms', () => {
    expect(panelToolbarSx).toMatchObject({ alignItems: 'center', flexWrap: 'wrap', gap: 1, minHeight: 48 })
    expect(actionGroupSx).toMatchObject({ ml: 'auto', alignItems: 'center', flexWrap: 'wrap' })
    expect(formActionRowSx).toMatchObject({ alignItems: 'flex-start', gap: 1 })
    expect(formActionRowSx).not.toHaveProperty('transform')
  })

  it('renders labelled and disabled controls with shared sizing and visible keyboard focus', () => {
    const markup = renderToStaticMarkup(<ThemeProvider theme={theme}>
      <Box sx={panelToolbarSx}>
        <TextField label="Input structure" value="" onChange={() => {}} />
        <Button variant="contained" startIcon={<AddIcon />}>Import files</Button>
        <IconButton aria-label="Add workspace" disabled><AddIcon /></IconButton>
      </Box>
    </ThemeProvider>)
    expect(markup).toContain('height:32px')
    expect(markup).toContain('aria-label="Add workspace"')
    expect(markup).toContain('disabled=""')
    expect(markup).toContain('Mui-focusVisible')
    expect(markup).toContain('outline-offset:2px')
    expect(markup).toContain('Input structure')
  })
})
