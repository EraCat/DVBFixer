import { createTheme } from '@mui/material/styles'
import { UI } from './ui/layout'

const PRIMARY_COLOR = '#4a76c4'
const focusRing = { outline: `2px solid ${PRIMARY_COLOR}`, outlineOffset: 2 }

export const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: PRIMARY_COLOR },
    secondary: { main: '#7c5cbf' },
    background: {
      default: '#e8ecf1',
      paper: '#f0f3f7',
    },
    divider: '#c9d1dc',
    text: {
      primary: '#1a1a2e',
      secondary: '#5a607a',
    },
    error: { main: '#c62828' },
    warning: { main: '#e68a00' },
    success: { main: '#2e7d32' },
    info: { main: '#1976d2' },
    action: {
      hover: 'rgba(74, 118, 196, 0.06)',
      selected: 'rgba(74, 118, 196, 0.12)',
    },
  },
  typography: {
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    fontSize: 12,
    body2: { fontSize: '0.75rem', lineHeight: 1.5 },
    caption: { fontSize: '0.7rem', lineHeight: 1.45 },
    subtitle2: { fontSize: '0.75rem', fontWeight: 600 },
  },
  shape: { borderRadius: 6 },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        'html, body, #root': {
          height: '100%',
          width: '100%',
          overflow: 'hidden',
        },
      },
    },
    MuiButton: {
      defaultProps: { size: 'small', disableElevation: true },
      styleOverrides: {
        root: {
          textTransform: 'none', fontSize: '0.75rem', fontWeight: 500, lineHeight: 1.25,
          height: UI.controlHeight, minHeight: UI.controlHeight, minWidth: 80,
          padding: '0 12px', whiteSpace: 'nowrap', flexShrink: 0, verticalAlign: 'middle',
          '&.Mui-focusVisible': focusRing,
        },
        startIcon: { marginLeft: 0, marginRight: 8, '& > *:nth-of-type(1)': { fontSize: UI.iconSize } },
        endIcon: { marginRight: 0, marginLeft: 8, '& > *:nth-of-type(1)': { fontSize: UI.iconSize } },
      },
    },
    MuiIconButton: {
      defaultProps: { size: 'small' },
      styleOverrides: {
        root: {
          width: UI.controlHeight, height: UI.controlHeight, padding: 6, flexShrink: 0,
          borderRadius: 6, verticalAlign: 'middle',
          '&.Mui-focusVisible': focusRing,
          '& .MuiSvgIcon-root': { fontSize: UI.iconSize },
        },
      },
    },
    MuiToggleButton: {
      defaultProps: { size: 'small' },
      styleOverrides: { root: {
        height: UI.controlHeight, minHeight: UI.controlHeight, minWidth: UI.controlHeight,
        padding: '0 12px', fontSize: '0.75rem', lineHeight: 1.25, textTransform: 'none',
        '&.Mui-focusVisible': focusRing,
      } },
    },
    MuiToggleButtonGroup: { defaultProps: { size: 'small' } },
    MuiMenuItem: { styleOverrides: { root: { fontSize: '0.75rem', minHeight: UI.controlHeight } } },
    MuiFormControl: { defaultProps: { size: 'small' } },
    MuiInputBase: { styleOverrides: { root: { fontSize: '0.75rem' } } },
    MuiOutlinedInput: {
      styleOverrides: {
        root: { '&:not(.MuiInputBase-multiline)': { height: UI.controlHeight } },
        input: { padding: '6px 12px', boxSizing: 'border-box' },
        inputMultiline: { padding: 0 },
      },
    },
    MuiInputLabel: { styleOverrides: { sizeSmall: {
      fontSize: '0.75rem', transform: 'translate(14px, 6px) scale(1)',
      '&.MuiInputLabel-shrink': { transform: 'translate(14px, -8px) scale(0.75)' },
    } } },
    MuiCheckbox: {
      defaultProps: { size: 'small' },
      styleOverrides: { root: { width: UI.controlHeight, height: UI.controlHeight, padding: 6 } },
    },
    MuiFormControlLabel: { styleOverrides: {
      root: { margin: 0, minHeight: UI.controlHeight, gap: 4 },
      label: { fontSize: '0.75rem', lineHeight: 1.4 },
    } },
    MuiTabs: { styleOverrides: { root: { minHeight: UI.controlHeight } } },
    MuiTab: { styleOverrides: { root: {
      minHeight: UI.controlHeight, padding: '6px 12px', fontSize: '0.75rem', textTransform: 'none',
    } } },
    MuiDialogActions: {
      defaultProps: { disableSpacing: true },
      styleOverrides: { root: { padding: 16, gap: 8, flexWrap: 'wrap' } },
    },
    MuiTableCell: {
      styleOverrides: {
        root: { fontSize: '0.75rem', padding: '6px 12px', borderColor: '#c9d1dc' },
        head: { fontWeight: 600, color: '#5a607a', backgroundColor: '#e8ecf1' },
      },
    },
    MuiTextField: {
      defaultProps: { size: 'small', variant: 'outlined' },
      styleOverrides: {
        root: { '& .MuiInputBase-input': { fontSize: '0.75rem' } },
      },
    },
    MuiChip: {
      styleOverrides: {
        root: { height: UI.compactHeight, fontSize: '0.7rem', maxWidth: '100%' },
      },
    },
    MuiTooltip: {
      defaultProps: { arrow: true },
      styleOverrides: {
        tooltip: { fontSize: '0.7rem' },
      },
    },
  },
})
