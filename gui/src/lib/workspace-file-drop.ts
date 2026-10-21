/** Only native file drags are captured; workspace/artifact reordering is untouched. */
export function listenForWorkspaceFileDrops(
  target: EventTarget,
  onHover: (hovering: boolean) => void,
  onFiles: (files: File[]) => void,
): () => void {
  let depth = 0
  const isFiles = (event: DragEvent) => Array.from(event.dataTransfer?.types || []).includes('Files')
  const reset = () => { depth = 0; onHover(false) }
  const enter = (event: Event) => {
    if (!isFiles(event as DragEvent)) return
    event.preventDefault()
    depth++
    onHover(true)
  }
  const over = (event: Event) => {
    const drag = event as DragEvent
    if (!isFiles(drag)) return
    drag.preventDefault()
    drag.stopPropagation()
    if (drag.dataTransfer) drag.dataTransfer.dropEffect = 'copy'
  }
  const leave = (event: Event) => {
    if (!isFiles(event as DragEvent)) return
    depth = Math.max(0, depth - 1)
    if (!depth) onHover(false)
  }
  const drop = (event: Event) => {
    const drag = event as DragEvent
    if (!isFiles(drag)) return
    drag.preventDefault()
    drag.stopPropagation()
    reset()
    const files = Array.from(drag.dataTransfer?.files || [])
    if (files.length) onFiles(files)
  }
  const listeners = { dragenter: enter, dragover: over, dragleave: leave, drop, dragend: reset, blur: reset }
  const options = { capture: true }
  for (const [type, listener] of Object.entries(listeners)) target.addEventListener(type, listener, options)
  return () => {
    for (const [type, listener] of Object.entries(listeners)) target.removeEventListener(type, listener, options)
  }
}
