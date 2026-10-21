import { Model, TabNode, TabSetNode } from 'flexlayout-react'
import { describe, expect, it } from 'vitest'
import { focusTextViewer } from './focus-text-viewer'

function model(includeText: boolean) {
  return Model.fromJson({ global: {}, borders: [], layout: { type: 'row', children: [
    { type: 'tabset', id: 'sidebar', children: [{ type: 'tab', component: 'library' }] },
    { type: 'tabset', id: 'workflows', children: [
      { type: 'tab', component: 'homology' },
      ...(includeText ? [{ type: 'tab' as const, component: 'text-viewer' }] : []),
    ] },
  ] } })
}

describe('Text Files navigation', () => {
  it.each([true, false])('selects a single text tab (already open=%s)', includeText => {
    const layout = model(includeText)
    focusTextViewer(layout)
    focusTextViewer(layout)
    const tabs: TabNode[] = []
    layout.visitNodes(node => { if (node instanceof TabNode && node.getComponent() === 'text-viewer') tabs.push(node) })
    expect(tabs).toHaveLength(1)
    expect(tabs[0].getParent()?.getId()).toBe('workflows')
    expect((layout.getNodeById('workflows') as TabSetNode).getSelectedNode()).toBe(tabs[0])
  })
})
