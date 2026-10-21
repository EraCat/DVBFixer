import { useEffect, useState } from 'react'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import { useWorkspaceStore } from '../stores/workspaceStore'
import { useWorkspaceImportStore } from '../stores/workspaceImportStore'
import { listenForWorkspaceFileDrops } from '../lib/workspace-file-drop'

export function WorkspaceFileDrop() {
  const [hovering, setHovering] = useState(false)
  const workspace = useWorkspaceStore(state => state.active)
  const importing = useWorkspaceImportStore(state => state.importing)
  const importFiles = useWorkspaceImportStore(state => state.importFiles)
  useEffect(() => listenForWorkspaceFileDrops(window, setHovering, files => {
    void importFiles(files)
  }), [importFiles])

  if (!hovering) return null
  return <Box role="status" sx={{
    position: 'fixed', inset: 12, zIndex: 1500, pointerEvents: 'none',
    border: '2px dashed', borderColor: 'primary.main', borderRadius: 2,
    bgcolor: 'rgba(235, 242, 255, 0.94)', display: 'flex', alignItems: 'center', justifyContent: 'center',
  }}>
    <Box sx={{ textAlign: 'center', p: 3, maxWidth: '80%' }}>
      <UploadFileIcon color="primary" sx={{ fontSize: 48, mb: 1 }} />
      <Typography variant="h6">
        {importing ? 'File import in progress' : workspace?.effectiveRole === 'reader' ? 'This workspace is read-only' : workspace ? 'Drop files to import' : 'Select a workspace first'}
      </Typography>
      <Typography color="text.secondary" sx={{ overflowWrap: 'anywhere' }}>
        {workspace ? workspace.name : 'Create or select a workspace before dropping files.'}
      </Typography>
    </Box>
  </Box>
}
