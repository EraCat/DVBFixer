import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Typography from '@mui/material/Typography'
import OpenInNewIcon from '@mui/icons-material/OpenInNew'
import type { ToolReportPreview } from '../lib/tool-output'

type OutputStream = 'stdout' | 'stderr'

export function ToolOutput({ stdout, stderr, reports = [], outputFile, onOpenFile, onOpenLog }: {
  stdout: string
  stderr: string
  onOpenLog?: (stream: OutputStream) => void
  reports?: ToolReportPreview[]
  outputFile?: string
  onOpenFile?: (file: string) => void
}) {
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
      {reports.map(report => <Box key={report.file} sx={{ p: 1, borderBottom: 1, borderColor: 'divider' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 0.5 }}>
          <Typography variant="caption" sx={{ fontWeight: 600, overflowWrap: 'anywhere' }}>
            Report · {report.file.split('/').pop()}
          </Typography>
          {onOpenFile && <Button size="small" onClick={() => onOpenFile(report.file)}
            endIcon={<OpenInNewIcon sx={{ fontSize: 12 }} />}
            sx={{ ml: 'auto', py: 0, fontSize: '0.65rem', whiteSpace: 'nowrap' }}>
            Open in Text Files
          </Button>}
        </Box>
        {report.error ? <Typography variant="caption" color="text.secondary">
          Preview unavailable: {report.error}. Open the report in Text Files to retry.
        </Typography> : <>
          <Box component="pre" sx={{
            m: 0, color: 'text.primary', fontFamily: 'ui-monospace, monospace',
            fontSize: '0.72rem', lineHeight: 1.5, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere',
          }}>{report.text || 'The report file is empty.'}</Box>
          {report.truncated && <Typography variant="caption" color="text.secondary">
            Preview shortened. Open in Text Files to read the complete report.
          </Typography>}
        </>}
      </Box>)}
      {outputFile && !reports.some(report => report.file === outputFile) && <Box sx={{ p: 1, display: 'flex', alignItems: 'center', gap: 1 }}>
        <Typography variant="caption" sx={{ overflowWrap: 'anywhere' }}>Output file · {outputFile.split('/').pop()}</Typography>
        {onOpenFile && <Button size="small" onClick={() => onOpenFile(outputFile)} sx={{ ml: 'auto', whiteSpace: 'nowrap', fontSize: '0.65rem' }}>Open in Text Files</Button>}
      </Box>}
      {!stdout && !stderr && !reports.length && !outputFile && <Typography variant="caption" color="text.secondary" sx={{ display: 'block', p: 1 }}>
        This run produced no console output or report file.
      </Typography>}
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
