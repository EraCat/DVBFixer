import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Typography from '@mui/material/Typography'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'

type OutputStream = 'stdout' | 'stderr'

export function ToolOutput({ stdout, stderr, onOpenLog }: {
  stdout: string
  stderr: string
  onOpenLog?: (stream: OutputStream) => void
}) {
  if (!stdout && !stderr) return null
  return <Box sx={{ mt: 1 }}>
    <Typography variant="caption" sx={{ fontWeight: 700 }}>Output &amp; diagnostics</Typography>
    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
      Reports and progress messages are not necessarily errors. Check the run status above.
    </Typography>
    <Box role="region" aria-label="Tool output and diagnostics" tabIndex={0} sx={{
      maxHeight: 'min(40vh, 360px)', overflow: 'auto', bgcolor: 'background.default',
      border: 1, borderColor: 'divider', borderRadius: 1,
      '&:focus-visible': { outline: '2px solid', outlineColor: 'primary.main' },
    }}>
      {(['stdout', 'stderr'] as const).map(stream => {
        const text = stream === 'stdout' ? stdout : stderr
        if (!text) return null
        return <Box key={stream} sx={{ p: 1, '& + &': { borderTop: 1, borderColor: 'divider' } }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
            <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600 }}>
              {stream === 'stdout' ? 'Standard output' : 'Diagnostics & messages (stderr)'}
            </Typography>
            {onOpenLog && <Button size="small" endIcon={<OpenInNewIcon sx={{ fontSize: 12 }} />}
              onClick={() => onOpenLog(stream)} sx={{ ml: 'auto', py: 0, fontSize: '0.65rem', whiteSpace: 'nowrap' }}>
              Open in Text Files
            </Button>}
          </Box>
          <Box component="pre" sx={{
            m: 0, color: 'text.primary', fontFamily: 'ui-monospace, monospace',
            fontSize: '0.72rem', lineHeight: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
          }}>{text}</Box>
        </Box>
      })}
    </Box>
  </Box>
}
