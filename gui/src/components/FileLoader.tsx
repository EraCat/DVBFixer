import { useCallback, useRef } from 'react'
import Button from '@mui/material/Button'

import UploadFileIcon from '@mui/icons-material/UploadFile'
import { useStructureStore } from '../stores/structureStore'
import { useSelectionStore } from '../stores/selectionStore'
import { useWorkspaceStore, workspaceFileUrl, type WorkspaceArtifact } from '../stores/workspaceStore'
import { structureMetaFromArtifact } from '../lib/workspace-metadata'
import { apiFetch } from '../lib/api-client'

function detectFormat(filename: string): 'pdb' | 'mmcif' {
  const lower = filename.toLowerCase()
  if (lower.endsWith('.cif') || lower.endsWith('.mmcif')) return 'mmcif'
  return 'pdb'
}

export function FileLoader() { // @dsp obj-a1000005
  const inputRef = useRef<HTMLInputElement>(null)
  const plugin = useStructureStore((s) => s.plugin)
  const secondaryPlugin = useStructureStore((s) => s.secondaryPlugin)
  const loadTargetSlot = useStructureStore((s) => s.loadTargetSlot)
  const setFileName = useStructureStore((s) => s.setFileName)
  const setSecondaryFileName = useStructureStore((s) => s.setSecondaryFileName)
  const setLoading = useStructureStore((s) => s.setLoading)
  const setMeta = useStructureStore((s) => s.setMeta)
  const setError = useStructureStore((s) => s.setError)
  const clearSelection = useSelectionStore((s) => s.clearSelection)
  const activeWorkspace = useWorkspaceStore((s) => s.active)
  const saveWorkspace = useWorkspaceStore((s) => s.save)
  const reloadWorkspace = useWorkspaceStore((s) => s.reload)
  const refreshWorkspaces = useWorkspaceStore((s) => s.refresh)
  const updateWorkspace = useWorkspaceStore((s) => s.update)

  const loadFile = useCallback(async (file: File) => {
    const targetPlugin = loadTargetSlot === 'secondary' ? secondaryPlugin : plugin
    if (!targetPlugin) {
      setError(
        loadTargetSlot === 'secondary'
          ? 'Open a "3D Structure (B)" tab first'
          : 'Viewer not initialized yet'
      )
      return
    }

    setLoading(true)
    setError(null)
    if (loadTargetSlot === 'primary') clearSelection()

    try {
      if (!activeWorkspace) throw new Error('Create or select a workspace before importing files')
      await saveWorkspace()
      const upload = await apiFetch(`/api/workspaces/${encodeURIComponent(activeWorkspace.id)}/import`, {
        method: 'POST', headers: { 'X-File-Name': encodeURIComponent(file.name) }, body: file,
      })
      const artifact = await upload.json() as WorkspaceArtifact & { error?: string }
      if (!upload.ok) throw new Error(artifact.error || `Import failed: HTTP ${upload.status}`)
      await reloadWorkspace()
      await refreshWorkspaces()
      const response = await apiFetch(workspaceFileUrl(activeWorkspace.id, artifact.file), { cache: 'no-store' })
      if (!response.ok) throw new Error(`Imported file cannot be read: HTTP ${response.status}`)
      const text = await response.text()
      const format = detectFormat(artifact.file)

      await targetPlugin.clear()
      const data = await targetPlugin.builders.data.rawData({ data: text, label: file.name })
      const trajectory = await targetPlugin.builders.structure.parseTrajectory(data, format)
      await targetPlugin.builders.structure.hierarchy.applyPreset(trajectory, 'default', {
        structure: { name: 'model', params: {} },
      })

      if (loadTargetSlot === 'secondary') {
        setSecondaryFileName(artifact.file)
        updateWorkspace({ secondaryFile: artifact.file })
      } else {
        setMeta(structureMetaFromArtifact(artifact))
        setFileName(artifact.file)
        updateWorkspace({ primaryFile: artifact.file })
      }
    } catch (err: any) {
      setError(`Failed to load file: ${err.message}`)
    } finally {
      setLoading(false)
    }
  }, [activeWorkspace, clearSelection, loadTargetSlot, plugin, refreshWorkspaces, reloadWorkspace, saveWorkspace, secondaryPlugin, setError, setFileName, setLoading, setMeta, setSecondaryFileName, updateWorkspace])

  const handleFileInput = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) loadFile(file)
    if (inputRef.current) inputRef.current.value = ''
  }, [loadFile])

  return (
    <>
      <Button
        variant="outlined"
        size="small"
        startIcon={<UploadFileIcon />}
        onClick={() => inputRef.current?.click()}
      >
        Import structure {secondaryPlugin ? `→ ${loadTargetSlot === 'secondary' ? 'B' : 'A'}` : ''}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept=".pdb,.cif,.mmcif"
        onChange={handleFileInput}
        style={{ display: 'none' }}
      />
    </>
  )
}
