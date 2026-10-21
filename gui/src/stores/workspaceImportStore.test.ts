import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useWorkspaceImportStore } from './workspaceImportStore'

const { state, apiFetch, setError } = vi.hoisted(() => ({
  state: {
    active: null as null | { id: string; effectiveRole: string },
    save: vi.fn(), reload: vi.fn(), refresh: vi.fn(),
  },
  apiFetch: vi.fn(), setError: vi.fn(),
}))
vi.mock('./workspaceStore', () => ({ useWorkspaceStore: { getState: () => state } }))
vi.mock('./structureStore', () => ({ useStructureStore: { getState: () => ({ setError }) } }))
vi.mock('../lib/api-client', () => ({ apiFetch }))

const files = () => [new File(['ATOM'], 'one.pdb'), new File(['>A'], 'two.fasta')]

describe('workspace file import', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    state.active = { id: 'project-a', effectiveRole: 'owner' }
    useWorkspaceImportStore.setState({ importing: false })
    apiFetch.mockResolvedValue({ ok: true, json: async () => ({}) })
  })

  it('imports every file into the active project without requiring a viewer', async () => {
    const batch = files()
    expect(await useWorkspaceImportStore.getState().importFiles(batch)).toBe(true)
    expect(state.save).toHaveBeenCalledOnce()
    expect(apiFetch).toHaveBeenCalledTimes(2)
    expect(apiFetch).toHaveBeenNthCalledWith(1, '/api/workspaces/project-a/import', {
      method: 'POST', headers: { 'X-File-Name': 'one.pdb' }, body: batch[0],
    })
    expect(state.reload).toHaveBeenCalledOnce()
    expect(state.refresh).toHaveBeenCalledOnce()
    expect(useWorkspaceImportStore.getState().importing).toBe(false)
  })

  it.each(['missing', 'reader'])('does not upload into a %s workspace', async kind => {
    state.active = kind === 'missing' ? null : { id: 'project-a', effectiveRole: 'reader' }
    expect(await useWorkspaceImportStore.getState().importFiles(files())).toBe(false)
    expect(apiFetch).not.toHaveBeenCalled()
    expect(setError).toHaveBeenCalledWith(expect.any(String))
  })

  it('pins the destination and does not reload a workspace selected mid-import', async () => {
    apiFetch.mockImplementation(async () => {
      state.active = { id: 'project-b', effectiveRole: 'owner' }
      return { ok: true, json: async () => ({}) }
    })
    await useWorkspaceImportStore.getState().importFiles(files())
    expect(apiFetch.mock.calls.map(call => call[0])).toEqual([
      '/api/workspaces/project-a/import', '/api/workspaces/project-a/import',
    ])
    expect(state.reload).not.toHaveBeenCalled()
    expect(state.refresh).toHaveBeenCalledOnce()
  })

  it('refreshes partial uploads and preserves the error', async () => {
    apiFetch.mockResolvedValueOnce({ ok: true, json: async () => ({}) })
      .mockResolvedValueOnce({ ok: false, json: async () => ({ error: 'Quota exceeded' }) })
    expect(await useWorkspaceImportStore.getState().importFiles(files())).toBe(false)
    expect(state.reload).toHaveBeenCalledOnce()
    expect(setError).toHaveBeenLastCalledWith('Quota exceeded')
    expect(useWorkspaceImportStore.getState().importing).toBe(false)
  })

  it('rejects a second batch while an import is in progress', async () => {
    let finish!: () => void
    state.save.mockImplementationOnce(() => new Promise<void>(resolve => { finish = resolve }))
    const first = useWorkspaceImportStore.getState().importFiles(files())
    expect(await useWorkspaceImportStore.getState().importFiles(files())).toBe(false)
    finish()
    await first
    expect(apiFetch).toHaveBeenCalledTimes(2)
  })
})
