import Box from '@mui/material/Box'
import Paper from '@mui/material/Paper'
import Typography from '@mui/material/Typography'
import Switch from '@mui/material/Switch'
import FormControlLabel from '@mui/material/FormControlLabel'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import { useStructureStore } from '../stores/structureStore'

/**
 * App-wide preferences. Currently a single toggle for auto-orienting
 * structures to their principal axes on load. Settings persist in
 * localStorage via the store (see `setAutoOrientOnLoad`).
 */
export function SettingsPanel() {
  const autoOrientOnLoad = useStructureStore(s => s.autoOrientOnLoad)
  const setAutoOrientOnLoad = useStructureStore(s => s.setAutoOrientOnLoad)
  const alignmentLabelMode = useStructureStore(s => s.alignmentLabelMode)
  const setAlignmentLabelMode = useStructureStore(s => s.setAlignmentLabelMode)

  return (
    <Box sx={{ p: 1.5, height: '100%', overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      <Box>
        <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>
          Viewer
        </Typography>
        <Paper variant="outlined" sx={{ p: 1.5, mt: 0.5 }}>
          <FormControlLabel
            control={
              <Switch
                size="small"
                checked={autoOrientOnLoad}
                onChange={(_e, checked) => setAutoOrientOnLoad(checked)}
              />
            }
            label={
              <Box>
                <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
                  Auto-orient on load
                </Typography>
                <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem' }}>
                  When ON, every loaded structure is rotated to its principal
                  axes (Mol*'s "Orient Axes" command). When OFF, the structure
                  keeps its authored orientation. Default: OFF.
                </Typography>
              </Box>
            }
            sx={{ alignItems: 'flex-start', m: 0, '& .MuiFormControlLabel-label': { ml: 0.5 } }}
          />
        </Paper>
      </Box>

      <Box>
        <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>
          Alignment
        </Typography>
        <Paper variant="outlined" sx={{ p: 1.5, mt: 0.5, display: 'flex', flexWrap: 'wrap', alignItems: 'flex-start', gap: 1.5 }}>
          <Box sx={{ flex: '1 1 160px', minWidth: 0 }}>
            <Typography variant="body2" sx={{ fontSize: '0.8rem' }}>
              Source label
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem' }}>
              What to display in the source-labels block above the alignment.
              Choose <strong>File</strong> for the file path / filename, or
              <strong> Name</strong> for the metadata name set in the Info tab.
            </Typography>
          </Box>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={alignmentLabelMode}
            onChange={(_e, v) => v && setAlignmentLabelMode(v)}
            sx={{ flexShrink: 0 }}
            aria-label="Alignment source label"
          >
            <ToggleButton value="file">File</ToggleButton>
            <ToggleButton value="name">Name</ToggleButton>
          </ToggleButtonGroup>
        </Paper>
      </Box>
    </Box>
  )
}
