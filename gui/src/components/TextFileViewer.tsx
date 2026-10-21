import { useEffect, useState } from 'react'
import Box from '@mui/material/Box'
import CircularProgress from '@mui/material/CircularProgress'
import Typography from '@mui/material/Typography'
import { useWorkspaceStore, workspaceFileUrl } from '../stores/workspaceStore'
import { apiFetch } from '../lib/api-client'
import { panelToolbarSx } from '../ui/layout'

export function TextFileViewer() {
  const preview = useWorkspaceStore(state => state.textPreview)
  const [text, setText] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!preview) { setText(''); setError(''); return }
    const controller = new AbortController()
    setLoading(true); setError('')
    apiFetch(workspaceFileUrl(preview.workspaceId, preview.file), { cache: 'no-store', signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error(`HTTP ${response.status}`); return response.text() })
      .then(setText).catch(reason => { if (reason.name !== 'AbortError') setError(reason.message || String(reason)) })
      .finally(() => setLoading(false))
    return () => controller.abort()
  }, [preview])

  if (!preview) return <Box sx={{ p: 2 }}><Typography variant="caption" color="text.secondary">Open a text-like workspace file to preview it here.</Typography></Box>
  return <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
    <Box sx={panelToolbarSx}><Typography variant="caption" sx={{ fontWeight: 700, overflowWrap: 'anywhere', minWidth: 0 }}>{preview.name} · {preview.file}</Typography></Box>
    {loading ? <CircularProgress size={18} sx={{ m: 2 }} /> : error ? <Typography color="error" sx={{ p: 1 }}>{error}</Typography> :
      <Box component="pre" sx={{ m: 0, p: 1.5, flex: 1, overflow: 'auto', whiteSpace: 'pre', fontFamily: 'ui-monospace, monospace', fontSize: 12, lineHeight: 1.45 }}>{text}</Box>}
  </Box>
}
