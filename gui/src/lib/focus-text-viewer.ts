import { Actions, DockLocation, Model, TabNode, TabSetNode } from 'flexlayout-react'

/** Reveal Text Files, recreating a closed tab next to Homology when possible. */
export function focusTextViewer(model: Model): void {
  let textTab: string | undefined
  let firstTabset: string | undefined
  let workflowTabset: string | undefined
  model.visitNodes(node => {
    if (node instanceof TabSetNode) firstTabset ??= node.getId()
    if (!(node instanceof TabNode)) return
    if (node.getComponent() === 'text-viewer') textTab ??= node.getId()
    if (node.getComponent() === 'homology') workflowTabset = node.getParent()?.getId()
  })
  const destination = workflowTabset || firstTabset
  if (textTab) model.doAction(Actions.selectTab(textTab))
  else if (destination) {
    model.doAction(Actions.addNode(
      { type: 'tab', name: 'Text Files', component: 'text-viewer' },
      destination, DockLocation.CENTER, -1, true,
    ))
  }
}
