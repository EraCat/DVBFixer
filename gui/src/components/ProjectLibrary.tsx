import { useCallback, useEffect, useRef, useState } from 'react'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import IconButton from '@mui/material/IconButton'
import List from '@mui/material/List'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemText from '@mui/material/ListItemText'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import TextField from '@mui/material/TextField'
import Dialog from '@mui/material/Dialog'
import DialogActions from '@mui/material/DialogActions'
import DialogContent from '@mui/material/DialogContent'
import DialogTitle from '@mui/material/DialogTitle'
import Divider from '@mui/material/Divider'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import AddIcon from '@mui/icons-material/Add'
import FolderOpenIcon from '@mui/icons-material/FolderOpen'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import ArrowUpwardIcon from '@mui/icons-material/ArrowUpward'
import ArrowDownwardIcon from '@mui/icons-material/ArrowDownward'
import DragIndicatorIcon from '@mui/icons-material/DragIndicator'
import { useStructureStore, type ViewerSlot } from '../stores/structureStore'
import { useWorkspaceStore, workspaceFileUrl, type WorkspaceArtifact, type WorkspaceManifest } from '../stores/workspaceStore'
import { useSelectionStore } from '../stores/selectionStore'
import { reorderVisibleArtifacts } from '../lib/workspace-order'
import { structureMetaFromArtifact } from '../lib/workspace-metadata'
import { apiFetch, downloadApiBlob, openApiBlob } from '../lib/api-client'
import { useWorkspaceImportStore } from '../stores/workspaceImportStore'

export function ProjectLibrary({ mode = 'library' }: { mode?: 'library' | 'workspace' }) {
  const uploadRef = useRef<HTMLInputElement>(null)
  const importFiles = useWorkspaceImportStore(state => state.importFiles)
  const importing = useWorkspaceImportStore(state => state.importing)
  const workspaces = useWorkspaceStore(state => state.workspaces)
  const active = useWorkspaceStore(state => state.active)
  const loading = useWorkspaceStore(state => state.loading)
  const error = useWorkspaceStore(state => state.error)
  const refresh = useWorkspaceStore(state => state.refresh)
  const activate = useWorkspaceStore(state => state.activate)
  const createWorkspace = useWorkspaceStore(state => state.createWorkspace)
  const reorderWorkspaces = useWorkspaceStore(state => state.reorderWorkspaces)
  const updateWorkspace = useWorkspaceStore(state => state.update)
  const updateArtifactMetadata = useWorkspaceStore(state => state.updateArtifactMetadata)
  const saveWorkspace = useWorkspaceStore(state => state.save)
  const reloadWorkspace = useWorkspaceStore(state => state.reload)
  const discardActive = useWorkspaceStore(state => state.discardActive)
  const setTextPreview = useWorkspaceStore(state => state.setTextPreview)
  const [selectedArtifacts, setSelectedArtifacts] = useState<Set<string>>(new Set())
  const selectionAnchor = useRef<number | null>(null)
  const [loadTarget, setLoadTarget] = useState<ViewerSlot>('primary')
  const [contextMenu, setContextMenu] = useState<{ mouseX: number; mouseY: number; kind: 'workspace' | 'artifact'; id: string; name: string } | null>(null)
  const [renameTarget, setRenameTarget] = useState<{ kind: 'workspace' | 'artifact'; id: string; name: string } | null>(null)
  const [renameDraft, setRenameDraft] = useState('')
  const [draggedWorkspace, setDraggedWorkspace] = useState<string | null>(null)
  const [draggedArtifact, setDraggedArtifact] = useState<string | null>(null)
  const [dropMarker, setDropMarker] = useState<{ kind: 'workspace' | 'artifact'; id: string; position: 'before' | 'after' } | null>(null)
  const [showNonPdb, setShowNonPdb] = useState(true)
  const plugin = useStructureStore(state => state.plugin)
  const secondaryPlugin = useStructureStore(state => state.secondaryPlugin)
  const setFileName = useStructureStore(state => state.setFileName)
  const setSecondaryFileName = useStructureStore(state => state.setSecondaryFileName)
  const setMeta = useStructureStore(state => state.setMeta)
  const setLoading = useStructureStore(state => state.setLoading)
  const setError = useStructureStore(state => state.setError)
  const clearSelection = useSelectionStore(state => state.clearSelection)

  const loadArtifact = useCallback(async (workspace: WorkspaceManifest, artifact: WorkspaceArtifact, slot: ViewerSlot) => {
    if (artifact.kind !== 'structure') {
      if (/\.(fasta|fa|faa|pir|aln|json|txt|html|csv|log|dat|top|itp|mdp|md|ya?ml|toml|xml|pml|py|sh|mol2|sdf)$/i.test(artifact.file)) {
        setTextPreview({ workspaceId: workspace.id, file: artifact.file, name: artifact.name })
        window.dispatchEvent(new Event('dvbfixer:open-text-viewer'))
      } else await openApiBlob(workspaceFileUrl(workspace.id, artifact.file))
      return
    }
    const target = slot === 'primary' ? plugin : secondaryPlugin
    if (!target) { setError(slot === 'primary' ? 'Open a 3D Structure tab first' : 'Open a 3D Structure (B) tab first'); return }
    setLoading(true); setError(null)
    if (slot === 'primary') clearSelection()
    try {
      const response = await apiFetch(workspaceFileUrl(workspace.id, artifact.file))
      if (!response.ok) throw new Error(`HTTP ${response.status}`)
      await target.clear()
      const data = await target.builders.data.rawData({ data: await response.text(), label: artifact.file })
      const format = /\.(cif|mmcif)$/i.test(artifact.file) ? 'mmcif' : 'pdb'
      const trajectory = await target.builders.structure.parseTrajectory(data, format)
      await target.builders.structure.hierarchy.applyPreset(trajectory, 'default', {
        structure: { name: 'model', params: {} },
      })
      if (slot === 'primary') {
        setMeta(structureMetaFromArtifact(artifact))
        setFileName(artifact.file)
        updateWorkspace({ primaryFile: artifact.file })
      } else {
        setSecondaryFileName(artifact.file)
        updateWorkspace({ secondaryFile: artifact.file })
      }
    } catch (reason: any) {
      setError(`Failed to load ${artifact.name}: ${reason.message || String(reason)}`)
    } finally { setLoading(false) }
  }, [clearSelection, plugin, secondaryPlugin, setError, setFileName, setLoading, setMeta, setSecondaryFileName, setTextPreview, updateWorkspace])

  useEffect(() => { setSelectedArtifacts(new Set()); selectionAnchor.current = null }, [active?.id])

  const openWorkspace = useCallback(async (id: string) => {
    const workspace = await activate(id)
    const primary = workspace.artifacts.find(item => item.file === workspace.primaryFile)
    const secondary = workspace.artifacts.find(item => item.file === workspace.secondaryFile)
    if (primary) await loadArtifact(workspace, primary, 'primary')
    else { setFileName(null); if (plugin) await plugin.clear() }
    if (secondary && secondaryPlugin) await loadArtifact(workspace, secondary, 'secondary')
    else { setSecondaryFileName(null); if (secondaryPlugin) await secondaryPlugin.clear() }
  }, [activate, loadArtifact, plugin, secondaryPlugin, setFileName, setSecondaryFileName])

  const removeContextItem = async (target: NonNullable<typeof contextMenu>) => {
    setContextMenu(null)
    setLoading(true); setError(null)
    try {
      if (target.kind === 'artifact') {
        if (!active) return
        await saveWorkspace()
        const targetIds = selectedArtifacts.has(target.id) ? [...selectedArtifacts] : [target.id]
        const artifacts = active.artifacts.filter(item => targetIds.includes(item.id))
        for (const artifact of artifacts) {
          const response = await apiFetch(`/api/workspaces/${encodeURIComponent(active.id)}/artifacts/${encodeURIComponent(artifact.id)}`, { method: 'DELETE' })
          if (!response.ok) {
            const body = await response.json().catch(() => ({}))
            throw new Error(body.error || `Delete failed for ${artifact.name}: HTTP ${response.status}`)
          }
        }
        if (artifacts.some(artifact => artifact.file === useStructureStore.getState().fileName)) {
          if (plugin) await plugin.clear()
          setFileName(null)
          clearSelection()
        }
        if (artifacts.some(artifact => artifact.file === useStructureStore.getState().secondaryFileName)) {
          if (secondaryPlugin) await secondaryPlugin.clear()
          setSecondaryFileName(null)
        }
        setSelectedArtifacts(new Set())
        selectionAnchor.current = null
        await reloadWorkspace()
        await refresh()
      } else {
        const wasActive = active?.id === target.id
        if (wasActive) await saveWorkspace()
        const response = await apiFetch(`/api/workspaces/${encodeURIComponent(target.id)}`, { method: 'DELETE' })
        if (!response.ok) {
          const body = await response.json().catch(() => ({}))
          throw new Error(body.error || `Delete failed: HTTP ${response.status}`)
        }
        if (wasActive) discardActive()
        await refresh()
        if (wasActive) {
          if (plugin) await plugin.clear()
          if (secondaryPlugin) await secondaryPlugin.clear()
          setFileName(null); setSecondaryFileName(null); clearSelection()
          const next = useWorkspaceStore.getState().workspaces[0]
          if (next) await openWorkspace(next.id)
          else await createWorkspace('Untitled workspace')
        }
      }
    } catch (reason: any) { setError(reason.message || String(reason)) }
    finally { setLoading(false) }
  }

  const renameContextItem = async (target: NonNullable<typeof renameTarget>, draft: string) => {
    const name = draft.trim()
    if (!name || name === target.name) return
    try {
      if (target.kind === 'artifact') {
        await updateArtifactMetadata(target.id, { name })
      } else {
        await saveWorkspace()
        const response = await apiFetch(`/api/workspaces/${encodeURIComponent(target.id)}/rename`, {
          method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }),
        })
        const body = await response.json().catch(() => ({}))
        if (!response.ok) throw new Error(body.error || `Rename failed: HTTP ${response.status}`)
        if (active?.id === target.id) await reloadWorkspace()
      }
      await refresh()
    } catch (reason: any) { setError(reason.message || String(reason)) }
  }

  const downloadContextItem = async (target: NonNullable<typeof contextMenu>) => {
    let url: string
    let filename: string
    if (target.kind === 'workspace') {
      url = `/api/workspaces/${encodeURIComponent(target.id)}/download`
      filename = `${target.name.replace(/[^a-zA-Z0-9._-]+/g, '_') || 'workspace'}.tar.gz`
    } else {
      if (!active) return
      const artifact = active.artifacts.find(item => item.id === target.id)
      if (!artifact) return
      url = workspaceFileUrl(active.id, artifact.file)
      filename = artifact.file.split('/').pop() || artifact.name
    }
    setContextMenu(null)
    try { await downloadApiBlob(url, filename) }
    catch (reason: any) { setError(reason.message || String(reason)) }
  }

  const moveWorkspace = async (draggedId: string, targetId: string, position: 'before' | 'after') => {
    if (draggedId === targetId) return
    const ids = workspaces.map(workspace => workspace.id)
    const from = ids.indexOf(draggedId)
    if (from < 0 || ids.indexOf(targetId) < 0) return
    const moved = ids.splice(from, 1)[0]
    const targetIndex = ids.indexOf(targetId)
    ids.splice(targetIndex + (position === 'after' ? 1 : 0), 0, moved)
    try { await reorderWorkspaces(ids) } catch (reason: any) { setError(reason.message || String(reason)) }
  }

  const moveArtifact = async (draggedId: string, targetId: string, position: 'before' | 'after') => {
    if (!active || draggedId === targetId) return
    const artifacts = [...active.artifacts]
    const from = artifacts.findIndex(artifact => artifact.id === draggedId)
    if (from < 0 || artifacts.findIndex(artifact => artifact.id === targetId) < 0) return
    const moved = artifacts.splice(from, 1)[0]
    const targetIndex = artifacts.findIndex(artifact => artifact.id === targetId)
    artifacts.splice(targetIndex + (position === 'after' ? 1 : 0), 0, moved)
    updateWorkspace({ artifacts })
    try { await useWorkspaceStore.getState().save() } catch (reason: any) { setError(reason.message || String(reason)) }
  }

  const reorderSelected = async (direction: -1 | 1) => {
    if (!active || !selectedArtifacts.size) return
    const visible = active.artifacts.filter(item => !item.hidden && (showNonPdb || /\.pdb$/i.test(item.file)))
    updateWorkspace({
      artifacts: reorderVisibleArtifacts(
        active.artifacts,
        visible.map(item => item.id),
        selectedArtifacts,
        direction,
      ),
    })
    await useWorkspaceStore.getState().save()
  }

  return <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
    <Box sx={{ px: 1, py: 0, height: 36, boxSizing: 'border-box', flexShrink: 0, borderBottom: 1, borderColor: 'divider', display: 'flex', gap: 0.5, alignItems: 'center' }}>
      <Typography variant="caption" noWrap title={active?.name} sx={{ fontWeight: 700, textTransform: 'uppercase', letterSpacing: 1, minWidth: 0 }}>{mode === 'library' ? 'Workspace' : active?.name || 'Workspace'}</Typography>
      {mode === 'library' ? (
        <Tooltip title="New workspace"><IconButton size="small" sx={{ ml: 'auto' }} onClick={() => createWorkspace()}><AddIcon fontSize="small" /></IconButton></Tooltip>
      ) : <>
        <input ref={uploadRef} hidden multiple type="file" onChange={event => {
          const files = Array.from(event.target.files || [])
          event.target.value = ''
          void importFiles(files)
        }} />
        <Tooltip title="Choose the 3D viewer in which selected structures open. This does not switch workspaces.">
          <ToggleButtonGroup aria-label="Target 3D viewer" size="small" exclusive value={loadTarget} onChange={(_event, value) => value && setLoadTarget(value)} sx={{ ml: 'auto', '& .MuiToggleButton-root': { minHeight: 24, py: 0, px: 1, fontSize: '0.68rem' } }}>
            <ToggleButton value="primary" title="Open selected structures in 3D viewer A" aria-label="Open selected structures in viewer A">A</ToggleButton>
            <ToggleButton value="secondary" disabled={!secondaryPlugin} title="Open selected structures in 3D viewer B (open the B tab first)" aria-label="Open selected structures in viewer B">B</ToggleButton>
          </ToggleButtonGroup>
        </Tooltip>
        <Tooltip title={active ? `Import files into ${active.name}` : 'Select a workspace to import files'}>
          <span>
            <Button variant="outlined" size="small" disabled={!active || active.effectiveRole === 'reader' || loading || importing}
              startIcon={<UploadFileIcon sx={{ fontSize: 16 }} />}
              onClick={() => uploadRef.current?.click()}
              sx={{ height: 28, px: 1, whiteSpace: 'nowrap', fontSize: '0.7rem' }}>
              {importing ? 'Importing…' : 'Import files'}
            </Button>
          </span>
        </Tooltip>
      </>}
    </Box>
    {error && <Typography variant="caption" color="error" sx={{ px: 1, py: 0.5 }}>{error}</Typography>}
    {loading && <CircularProgress size={16} sx={{ m: 1 }} />}
    {mode === 'library' && <List dense disablePadding sx={{ flex: 1, overflow: 'auto' }}>
      {workspaces.map((workspace, index) => <ListItemButton key={workspace.id} selected={active?.id === workspace.id} onClick={() => openWorkspace(workspace.id)}
        onDragOver={event => { event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = 'move'; const rect = event.currentTarget.getBoundingClientRect(); setDropMarker({ kind: 'workspace', id: workspace.id, position: event.clientY < rect.top + rect.height / 2 ? 'before' : 'after' }) }}
        onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropMarker(null) }}
        onDrop={event => { event.preventDefault(); event.stopPropagation(); const position = dropMarker?.kind === 'workspace' && dropMarker.id === workspace.id ? dropMarker.position : 'before'; if (draggedWorkspace) moveWorkspace(draggedWorkspace, workspace.id, position).catch(() => {}); setDraggedWorkspace(null); setDropMarker(null) }}
        onContextMenu={event => { event.preventDefault(); setContextMenu({ mouseX: event.clientX + 2, mouseY: event.clientY - 6, kind: 'workspace', id: workspace.id, name: workspace.name }) }}
        sx={{
          py: 0.2,
          '& .MuiListItemText-root': { my: 0.25 },
          bgcolor: active?.id === workspace.id ? 'rgba(29,50,97,0.24)' : index % 2 ? 'rgba(29,50,97,0.045)' : 'transparent',
          '&.Mui-selected': { bgcolor: 'rgba(29,50,97,0.24)' },
          '&.Mui-selected:hover': { bgcolor: 'rgba(29,50,97,0.31)' },
          borderTop: '2px solid', borderBottom: '2px solid',
          borderTopColor: dropMarker?.kind === 'workspace' && dropMarker.id === workspace.id && dropMarker.position === 'before' ? 'primary.main' : 'transparent',
          borderBottomColor: dropMarker?.kind === 'workspace' && dropMarker.id === workspace.id && dropMarker.position === 'after' ? 'primary.main' : 'transparent',
        }}>
        <Box component="span" draggable onMouseDown={event => event.stopPropagation()}
          onClick={event => event.stopPropagation()}
          onDragStart={event => { event.stopPropagation(); event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', workspace.id); setDraggedWorkspace(workspace.id) }}
          onDragEnd={event => { event.stopPropagation(); setDraggedWorkspace(null); setDropMarker(null) }}
          sx={{ display: 'inline-flex', cursor: 'grab', color: 'text.disabled', mr: 0.5, '&:active': { cursor: 'grabbing' } }}>
          <DragIndicatorIcon sx={{ fontSize: 16 }} />
        </Box>
        <FolderOpenIcon sx={{ fontSize: 16, mr: 1 }} />
        <ListItemText primary={workspace.name} secondary={`${workspace.artifactCount} files`} />
      </ListItemButton>)}
    </List>}
    {mode === 'workspace' && active && <>
      <Box sx={{ px: 1, borderBottom: 1, borderColor: 'divider', display: 'flex', alignItems: 'center' }}><Typography variant="caption" sx={{ fontWeight: 700, color: 'text.secondary' }}>FILES</Typography>
        <Divider orientation="vertical" flexItem sx={{ mx: 1 }} />
        <Button size="small" onClick={() => setShowNonPdb(show => !show)}>{showNonPdb ? 'Hide non-PDB files' : 'Show non-PDB files'}</Button>
        {!!selectedArtifacts.size && <Typography variant="caption" color="primary">{selectedArtifacts.size} selected</Typography>}
        <Box sx={{ ml: 'auto', display: 'flex' }}>
          <Tooltip title="Move selected files up"><span><IconButton size="small" disabled={!selectedArtifacts.size} onClick={() => reorderSelected(-1)}><ArrowUpwardIcon fontSize="inherit" /></IconButton></span></Tooltip>
          <Tooltip title="Move selected files down"><span><IconButton size="small" disabled={!selectedArtifacts.size} onClick={() => reorderSelected(1)}><ArrowDownwardIcon fontSize="inherit" /></IconButton></span></Tooltip>
        </Box>
      </Box>
      <List dense disablePadding sx={{ flex: 1, overflow: 'auto' }}>
        {active.artifacts.filter(artifact => !artifact.hidden && (showNonPdb || /\.pdb$/i.test(artifact.file))).map((artifact, index, visible) => <ListItemButton key={artifact.id} selected={selectedArtifacts.has(artifact.id)}
          onDragOver={event => { event.preventDefault(); event.stopPropagation(); event.dataTransfer.dropEffect = 'move'; const rect = event.currentTarget.getBoundingClientRect(); setDropMarker({ kind: 'artifact', id: artifact.id, position: event.clientY < rect.top + rect.height / 2 ? 'before' : 'after' }) }}
          onDragLeave={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDropMarker(null) }}
          onDrop={event => { event.preventDefault(); event.stopPropagation(); const position = dropMarker?.kind === 'artifact' && dropMarker.id === artifact.id ? dropMarker.position : 'before'; if (draggedArtifact) moveArtifact(draggedArtifact, artifact.id, position).catch(() => {}); setDraggedArtifact(null); setDropMarker(null) }}
          onClick={event => {
          if (event.shiftKey && selectionAnchor.current !== null) {
            const start = Math.min(selectionAnchor.current, index); const end = Math.max(selectionAnchor.current, index)
            setSelectedArtifacts(current => new Set([...current, ...visible.slice(start, end + 1).map(item => item.id)]))
          } else if (event.ctrlKey || event.metaKey) {
            setSelectedArtifacts(current => { const next = new Set(current); if (next.has(artifact.id)) next.delete(artifact.id); else next.add(artifact.id); return next })
            selectionAnchor.current = index
          } else {
            setSelectedArtifacts(new Set([artifact.id])); selectionAnchor.current = index
            loadArtifact(active, artifact, loadTarget).catch(() => {})
          }
        }} sx={{
          pl: 2,
          bgcolor: selectedArtifacts.has(artifact.id) ? 'rgba(29,50,97,0.24)' : index % 2 ? 'rgba(29,50,97,0.045)' : 'transparent',
          '&.Mui-selected': { bgcolor: 'rgba(29,50,97,0.24)' },
          '&.Mui-selected:hover': { bgcolor: 'rgba(29,50,97,0.31)' },
          borderTop: '2px solid', borderBottom: '2px solid',
          borderTopColor: dropMarker?.kind === 'artifact' && dropMarker.id === artifact.id && dropMarker.position === 'before' ? 'primary.main' : 'transparent',
          borderBottomColor: dropMarker?.kind === 'artifact' && dropMarker.id === artifact.id && dropMarker.position === 'after' ? 'primary.main' : 'transparent',
        }}
          onContextMenu={event => { event.preventDefault(); setContextMenu({ mouseX: event.clientX + 2, mouseY: event.clientY - 6, kind: 'artifact', id: artifact.id, name: artifact.name }) }}>
          <Box component="span" draggable onMouseDown={event => event.stopPropagation()}
            onClick={event => event.stopPropagation()}
            onDragStart={event => { event.stopPropagation(); event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', artifact.id); setDraggedArtifact(artifact.id) }}
            onDragEnd={event => { event.stopPropagation(); setDraggedArtifact(null); setDropMarker(null) }}
            sx={{ display: 'inline-flex', cursor: 'grab', color: 'text.disabled', mr: 0.5, '&:active': { cursor: 'grabbing' } }}>
            <DragIndicatorIcon sx={{ fontSize: 16 }} />
          </Box>
          <ListItemText primary={artifact.name} />
        </ListItemButton>)}
        {!active.artifacts.length && <Box sx={{ p: 2, textAlign: 'center' }}><Typography variant="caption" color="text.secondary">Import files to begin.</Typography></Box>}
      </List>
    </>}
    <Button size="small" onClick={() => refresh()} sx={{ m: 0.5 }}>Refresh</Button>
    <Menu open={!!contextMenu} onClose={() => setContextMenu(null)} anchorReference="anchorPosition"
      anchorPosition={contextMenu ? { top: contextMenu.mouseY, left: contextMenu.mouseX } : undefined}>
      <MenuItem onClick={() => {
        if (!contextMenu) return
        setRenameTarget({ kind: contextMenu.kind, id: contextMenu.id, name: contextMenu.name })
        setRenameDraft(contextMenu.name)
        setContextMenu(null)
      }}>Rename</MenuItem>
      <MenuItem onClick={() => contextMenu && downloadContextItem(contextMenu)}>
        Download{contextMenu?.kind === 'workspace' ? ' archive' : ''}
      </MenuItem>
      <MenuItem onClick={() => contextMenu && removeContextItem(contextMenu)}>Move {contextMenu?.kind === 'workspace' ? 'workspace' : contextMenu && selectedArtifacts.has(contextMenu.id) && selectedArtifacts.size > 1 ? `${selectedArtifacts.size} selected files` : 'file'} to trash</MenuItem>
    </Menu>
    <Dialog open={!!renameTarget} onClose={() => setRenameTarget(null)} fullWidth maxWidth="xs">
      <DialogTitle>Rename {renameTarget?.kind}</DialogTitle>
      <DialogContent>
        <TextField autoFocus fullWidth size="small" label="Name" value={renameDraft}
          onChange={event => setRenameDraft(event.target.value)} sx={{ mt: 1 }}
          onKeyDown={event => {
            if (event.key !== 'Enter' || !renameTarget) return
            renameContextItem(renameTarget, renameDraft).finally(() => setRenameTarget(null))
          }} />
      </DialogContent>
      <DialogActions>
        <Button onClick={() => setRenameTarget(null)}>Cancel</Button>
        <Button variant="contained" disabled={!renameDraft.trim()} onClick={() => {
          if (!renameTarget) return
          renameContextItem(renameTarget, renameDraft).finally(() => setRenameTarget(null))
        }}>Rename</Button>
      </DialogActions>
    </Dialog>
  </Box>
}

export function WorkspacePanel() {
  return <ProjectLibrary mode="workspace" />
}
