import { create } from 'zustand'
import { apiFetch } from '../lib/api-client'
import { useWorkspaceStore } from './workspaceStore'
import { useStructureStore } from './structureStore'

interface WorkspaceImportState {
  importing: boolean
  importFiles: (files: Iterable<File>) => Promise<boolean>
}

/** Shared by the file picker and OS file drops; never imports into the viewer. */
export const useWorkspaceImportStore = create<WorkspaceImportState>((set, get) => ({
  importing: false,
  importFiles: async files => {
    const batch = Array.from(files)
    if (!batch.length || get().importing) return false
    const workspace = useWorkspaceStore.getState()
    const destination = workspace.active
    const { setError } = useStructureStore.getState()
    if (!destination) {
      setError('Select or create a workspace before importing files')
      return false
    }
    if (destination.effectiveRole === 'reader') {
      setError('This workspace is read-only')
      return false
    }
    set({ importing: true })
    setError(null)
    let imported = 0
    let failure: string | null = null
    try {
      await workspace.save()
      for (const file of batch) {
        const response = await apiFetch(`/api/workspaces/${encodeURIComponent(destination.id)}/import`, {
          method: 'POST', headers: { 'X-File-Name': encodeURIComponent(file.name) }, body: file,
        })
        const body = await response.json().catch(() => ({}))
        if (!response.ok) throw new Error(body.error || `Import failed: ${file.name} (HTTP ${response.status})`)
        imported++
      }
    } catch (error) {
      failure = error instanceof Error ? error.message : String(error)
    } finally {
      // A partial import is still real data. Refresh it even if a later file
      // failed, but never reload a different workspace selected mid-upload.
      try {
        if (imported && useWorkspaceStore.getState().active?.id === destination.id) await workspace.reload()
        if (imported) await workspace.refresh()
      } catch (error) {
        failure ||= error instanceof Error ? error.message : String(error)
      }
      set({ importing: false })
    }
    if (failure) setError(failure)
    return failure === null
  },
}))
