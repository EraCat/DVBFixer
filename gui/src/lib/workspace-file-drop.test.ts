import { describe, expect, it, vi } from 'vitest'
import { listenForWorkspaceFileDrops } from './workspace-file-drop'

function drag(type: string, files: File[] = [], types = ['Files']) {
  const event = new Event(type, { cancelable: true })
  Object.defineProperty(event, 'dataTransfer', { value: { types, files, dropEffect: 'none' } })
  return event
}

describe('native workspace file drops', () => {
  it('captures files and prevents browser navigation', () => {
    const target = new EventTarget()
    const hover = vi.fn()
    const imported = vi.fn()
    const cleanup = listenForWorkspaceFileDrops(target, hover, imported)
    const files = [new File(['ATOM'], 'input.pdb'), new File(['>A'], 'target.fasta')]
    target.dispatchEvent(drag('dragenter'))
    const over = drag('dragover')
    target.dispatchEvent(over)
    expect(over.defaultPrevented).toBe(true)
    const drop = drag('drop', files)
    target.dispatchEvent(drop)
    expect(drop.defaultPrevented).toBe(true)
    expect(imported).toHaveBeenCalledExactlyOnceWith(files)
    expect(hover).toHaveBeenLastCalledWith(false)
    cleanup()
    target.dispatchEvent(drag('drop', files))
    expect(imported).toHaveBeenCalledTimes(1)
  })

  it('leaves internal file/workspace reordering and text drags alone', () => {
    const target = new EventTarget()
    const imported = vi.fn()
    const hover = vi.fn()
    listenForWorkspaceFileDrops(target, hover, imported)
    for (const type of ['dragenter', 'dragover', 'drop']) {
      const event = drag(type, [], ['text/plain'])
      target.dispatchEvent(event)
      expect(event.defaultPrevented).toBe(false)
    }
    expect(imported).not.toHaveBeenCalled()
    expect(hover).not.toHaveBeenCalled()
  })

  it('keeps the overlay during nested enter/leave and resets on blur', () => {
    const target = new EventTarget()
    const hover = vi.fn()
    listenForWorkspaceFileDrops(target, hover, vi.fn())
    target.dispatchEvent(drag('dragenter'))
    target.dispatchEvent(drag('dragenter'))
    target.dispatchEvent(drag('dragleave'))
    expect(hover).toHaveBeenLastCalledWith(true)
    target.dispatchEvent(new Event('blur'))
    expect(hover).toHaveBeenLastCalledWith(false)
  })
})
