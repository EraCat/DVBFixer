import { useCallback, useState, useEffect } from 'react'
import Box from '@mui/material/Box'
import { compactIconButtonSx } from '../ui/layout'
import Typography from '@mui/material/Typography'
import IconButton from '@mui/material/IconButton'
import Collapse from '@mui/material/Collapse'
import Tooltip from '@mui/material/Tooltip'
import VisibilityIcon from '@mui/icons-material/Visibility'
import VisibilityOffIcon from '@mui/icons-material/VisibilityOff'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import HubIcon from '@mui/icons-material/Hub'
import { useStructureStore } from '../stores/structureStore'
import { useSelectionStore } from '../stores/selectionStore'
import { setSubtreeVisibility } from 'molstar/lib/mol-plugin/behavior/static/state'
import { StructureProperties as SP, StructureElement, StructureSelection, QueryContext } from 'molstar/lib/mol-model/structure'
import { MolScriptBuilder as MS } from 'molstar/lib/mol-script/language/builder'
import { compile } from 'molstar/lib/mol-script/runtime/query/compiler'
import { OrderedSet } from 'molstar/lib/mol-data/int'
import { focusInterfaceForChain, clearInterfaceFocus } from '../lib/molstar-helpers'

interface ChainItem {
  chainId: string
  compIds: string[]
  residueCount: number
  atomCount: number
}

interface ComponentGroup {
  ref: string
  label: string
  category: string
  chains: ChainItem[]
  totalAtoms: number
  isHidden: boolean
}

const CATEGORY_CONFIG: Record<string, { label: string; color: string }> = {
  polymer: { label: 'Polymers', color: '#2e7d32' },
  ligand: { label: 'Ligands', color: '#e68a00' },
  ion: { label: 'Ions', color: '#c62828' },
  water: { label: 'Water', color: '#1565c0' },
  other: { label: 'Other', color: '#5a607a' },
}

const CATEGORY_ORDER = ['polymer', 'ligand', 'ion', 'water', 'other']

function categorize(label: string): string {
  const l = label.toLowerCase()
  if (l.includes('polymer') || l.includes('protein') || l.includes('nucleic')) return 'polymer'
  if (l.includes('water')) return 'water'
  if (l.includes('ion')) return 'ion'
  if (l.includes('ligand') || l.includes('non-standard')) return 'ligand'
  return 'other'
}

function extractChainsFromStructure(structure: any): ChainItem[] {
  const chainMap = new Map<string, ChainItem>()
  const loc = StructureElement.Location.create(structure)
  const seenRes = new Set<string>()

  for (let i = 0; i < structure.units.length; i++) {
    const unit = structure.units[i]
    const { elements } = unit
    loc.unit = unit

    for (let j = 0, jl = OrderedSet.size(elements); j < jl; j++) {
      loc.element = OrderedSet.getAt(elements, j)
      const chainId = SP.chain.label_asym_id(loc)
      const compId = SP.atom.label_comp_id(loc)
      const seqId = SP.residue.label_seq_id(loc)

      if (!chainMap.has(chainId)) {
        chainMap.set(chainId, { chainId, compIds: [], residueCount: 0, atomCount: 0 })
      }
      const chain = chainMap.get(chainId)!
      chain.atomCount++

      const rk = `${chainId}:${seqId}:${compId}`
      if (!seenRes.has(rk)) {
        seenRes.add(rk)
        chain.residueCount++
        if (!chain.compIds.includes(compId)) chain.compIds.push(compId)
      }
    }
  }

  return Array.from(chainMap.values()).sort((a, b) => a.chainId.localeCompare(b.chainId))
}

export function ElementsTable() {
  const plugin = useStructureStore((s) => s.plugin)
  const [components, setComponents] = useState<ComponentGroup[]>([])
  const [expanded, setExpanded] = useState<Set<string>>(new Set(['polymer']))
  const [, setTick] = useState(0)

  useEffect(() => {
    if (!plugin) return

    const update = () => {
      const comps: ComponentGroup[] = []

      for (const struct of plugin.managers.structure.hierarchy.current.structures) {
        for (const comp of struct.components) {
          const cell = comp.cell
          const structure = cell.obj?.data
          if (!structure) continue

          // Skip focus-representation components (created by Zoom/focus)
          const tags = cell.transform.tags ?? []
          if (tags.some((t: string) => t.startsWith('structure-focus-'))) continue

          const label = cell.obj?.label || comp.key || 'Unknown'
          const ref = cell.transform.ref
          const chains = extractChainsFromStructure(structure)
          const totalAtoms = chains.reduce((s, c) => s + c.atomCount, 0)

          comps.push({
            ref, label,
            category: categorize(label),
            chains,
            totalAtoms,
            isHidden: !!cell.state?.isHidden,
          })
        }
      }
      setComponents(comps)
    }

    update()
    const sub1 = plugin.managers.structure.hierarchy.behaviors.selection.subscribe(update)
    const sub2 = plugin.state.data.events.cell.stateUpdated.subscribe(() => { setTick(t => t + 1); update() })
    return () => { sub1.unsubscribe(); sub2.unsubscribe() }
  }, [plugin])

  const toggleExpand = useCallback((key: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }, [])

  const toggleVisibility = useCallback((ref: string, hidden: boolean) => {
    if (!plugin) return
    setSubtreeVisibility(plugin.state.data, ref, !hidden)
  }, [plugin])

  const toggleCategoryVisibility = useCallback((category: string) => {
    if (!plugin) return
    const items = components.filter(c => c.category === category)
    const allHidden = items.every(i => i.isHidden)
    for (const item of items) {
      setSubtreeVisibility(plugin.state.data, item.ref, !allHidden)
    }
  }, [plugin, components])

  const clearStoreSelection = useSelectionStore((s) => s.clearSelection)
  const focusedChainId = useStructureStore((s) => s.focusedChainId)
  const focusedCategory = useStructureStore((s) => s.focusedCategory)
  const setFocusedChain = useStructureStore((s) => s.setFocusedChain)

  const handleInterfaceClick = useCallback((chainId: string, category: string) => {
    if (!plugin) return
    const isActive = focusedChainId === chainId && focusedCategory === category
    if (isActive) {
      setFocusedChain(null)
      clearInterfaceFocus(plugin).catch(err => console.warn('[interface] clear failed:', err))
      return
    }
    setFocusedChain(chainId, category)
    focusInterfaceForChain(plugin, chainId, category, 5)
      .catch(err => console.warn('[interface] focus failed:', err))
  }, [plugin, focusedChainId, focusedCategory, setFocusedChain])

  const selectChainInComponent = useCallback((ref: string, chainId: string) => {
    if (!plugin) return

    // Clear sequence tab selection first
    clearStoreSelection()

    const cell = plugin.state.data.cells.get(ref)
    const structure = cell?.obj?.data
    if (!structure) return

    const query = MS.struct.generator.atomGroups({
      'chain-test': MS.core.rel.eq([
        MS.struct.atomProperty.macromolecular.label_asym_id(),
        chainId,
      ]),
    })

    const compiled = compile<StructureSelection>(query)
    const selection = compiled(new QueryContext(structure))
    const loci = StructureSelection.toLociWithSourceUnits(selection)

    plugin.managers.interactivity.lociSelects.deselectAll()
    plugin.managers.interactivity.lociSelects.select({ loci })
    plugin.managers.structure.focus.setFromLoci(loci)

    // Actually move the camera to the chain. If the secondary viewer is open
    // and sync is on, the snapshot would mirror over and overwrite its
    // independent camera — temporarily suppress sync, then restore it after
    // the camera animation settles.
    const store = useStructureStore.getState()
    const needSyncSuppression = !!store.secondaryPlugin && store.cameraSyncEnabled
    if (needSyncSuppression) store.setCameraSyncEnabled(false)
    plugin.managers.camera.focusLoci(loci)
    if (needSyncSuppression) {
      setTimeout(() => useStructureStore.getState().setCameraSyncEnabled(true), 500)
    }
  }, [plugin, clearStoreSelection])


  if (components.length === 0) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>Load a structure to see its elements</Typography>
      </Box>
    )
  }

  // Group by category
  const grouped = new Map<string, ComponentGroup[]>()
  for (const comp of components) {
    if (!grouped.has(comp.category)) grouped.set(comp.category, [])
    grouped.get(comp.category)!.push(comp)
  }

  return (
    <Box sx={{ height: '100%', overflow: 'auto' }}>
      {CATEGORY_ORDER.map(cat => {
        const catComps = grouped.get(cat)
        if (!catComps || catComps.length === 0) return null
        const cfg = CATEGORY_CONFIG[cat]
        const isCatExpanded = expanded.has(cat)
        const allHidden = catComps.every(c => c.isHidden)
        const totalAtoms = catComps.reduce((s, c) => s + c.totalAtoms, 0)
        const totalChains = catComps.reduce((s, c) => s + c.chains.length, 0)

        return (
          <Box key={cat}>
            {/* ── Category header ── */}
            <Box
              onClick={() => toggleExpand(cat)}
              sx={{
                display: 'flex', alignItems: 'center',
                px: 0.5, py: 0.5,
                cursor: 'pointer',
                bgcolor: 'action.hover',
                borderBottom: '1px solid', borderColor: 'divider',
                '&:hover': { bgcolor: 'action.selected' },
                userSelect: 'none',
              }}
            >
              <IconButton
                aria-label={`Toggle ${cfg.label} visibility`}
                size="small"
                onClick={(e) => { e.stopPropagation(); toggleCategoryVisibility(cat) }}
                sx={{ ...compactIconButtonSx, mr: 0.5 }}
              >
                {allHidden
                  ? <VisibilityOffIcon sx={{ fontSize: 14, color: 'text.secondary' }} />
                  : <VisibilityIcon sx={{ fontSize: 14 }} />
                }
              </IconButton>
              {isCatExpanded
                ? <ExpandMoreIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
                : <ChevronRightIcon sx={{ fontSize: 16, color: 'text.secondary' }} />
              }
              <Box sx={{ width: 8, height: 8, borderRadius: '50%', bgcolor: cfg.color, mx: 0.5, flexShrink: 0 }} />
              <Typography variant="caption" sx={{ fontWeight: 700, fontSize: '0.7rem', flex: 1 }}>
                {cfg.label}
              </Typography>
              <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.6rem', mr: 0.5 }}>
                {totalChains} chain{totalChains !== 1 ? 's' : ''} · {totalAtoms.toLocaleString()}
              </Typography>
            </Box>

            {/* ── Expanded: each component, split by chain ── */}
            <Collapse in={isCatExpanded}>
              {catComps.map(comp => (
                <Box key={comp.ref}>
                  {comp.chains.map(chain => (
                    <Box
                      key={`${comp.ref}:${chain.chainId}`}
                      onClick={() => selectChainInComponent(comp.ref, chain.chainId)}
                      sx={{
                        display: 'flex', alignItems: 'center',
                        pl: 1, pr: 1, py: 0.35,
                        cursor: 'pointer',
                        opacity: comp.isHidden ? 0.3 : 1,
                        borderBottom: '1px solid', borderColor: 'divider',
                        transition: 'opacity 150ms, background-color 100ms',
                        '&:hover': { bgcolor: 'action.hover' },
                      }}
                    >
                      <IconButton
                        aria-label={`Toggle chain ${chain.chainId} visibility`}
                        size="small"
                        onClick={(e) => { e.stopPropagation(); toggleVisibility(comp.ref, comp.isHidden) }}
                        sx={{ ...compactIconButtonSx, mr: 0.5 }}
                      >
                        {comp.isHidden
                          ? <VisibilityOffIcon sx={{ fontSize: 13, color: 'text.secondary' }} />
                          : <VisibilityIcon sx={{ fontSize: 13 }} />
                        }
                      </IconButton>
                      <Typography variant="caption" sx={{
                        fontWeight: 700, fontSize: '0.7rem',
                        minWidth: 60, flexShrink: 0,
                      }}>
                        Chain {chain.chainId}
                      </Typography>
                      <Box sx={{ flex: 1, minWidth: 0 }}>
                        <Typography variant="caption" sx={{ fontSize: '0.6rem', color: 'text.secondary', fontFamily: 'monospace' }}>
                          {chain.compIds.length <= 4
                            ? chain.compIds.join(', ')
                            : `${chain.compIds.slice(0, 3).join(', ')} +${chain.compIds.length - 3}`
                          }
                        </Typography>
                      </Box>
                      <Typography variant="caption" sx={{
                        fontFamily: 'monospace', fontSize: '0.6rem', color: 'text.secondary',
                        whiteSpace: 'nowrap', ml: 0.5,
                      }}>
                        {chain.residueCount} res · {chain.atomCount.toLocaleString()}
                      </Typography>
                      {(() => {
                        const isActive = focusedChainId === chain.chainId && focusedCategory === cat
                        const tooltipLabel = isActive
                          ? 'Clear interface focus'
                          : `Show interface for ${cat} chain ${chain.chainId} (5 Å)`
                        return (
                          <Tooltip title={tooltipLabel} placement="top">
                            <IconButton
                              aria-label={tooltipLabel}
                              aria-pressed={isActive}
                              size="small"
                              onClick={(e) => { e.stopPropagation(); handleInterfaceClick(chain.chainId, cat) }}
                              sx={isActive
                                ? {
                                    ...compactIconButtonSx, ml: 0.5,
                                    bgcolor: 'primary.main',
                                    color: 'primary.contrastText',
                                    border: '1px solid',
                                    borderColor: 'primary.main',
                                    boxShadow: '0 0 0 2px rgba(74, 118, 196, 0.25)',
                                    '&:hover': { bgcolor: 'primary.dark' },
                                  }
                                : {
                                    ...compactIconButtonSx, ml: 0.5,
                                    color: 'text.secondary',
                                    bgcolor: 'transparent',
                                    border: '1px solid transparent',
                                    '&:hover': { color: 'primary.main', bgcolor: 'action.hover' },
                                  }
                              }
                            >
                              <HubIcon sx={{ fontSize: 13 }} />
                            </IconButton>
                          </Tooltip>
                        )
                      })()}
                    </Box>
                  ))}
                </Box>
              ))}
            </Collapse>
          </Box>
        )
      })}
    </Box>
  )
}
