import { useCallback, useRef, useEffect, useState } from 'react'
import Box from '@mui/material/Box'
import { actionGroupSx, panelToolbarSx } from '../ui/layout'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import Tooltip from '@mui/material/Tooltip'
import IconButton from '@mui/material/IconButton'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import ClearIcon from '@mui/icons-material/Deselect'
import ZoomInIcon from '@mui/icons-material/CenterFocusStrong'
import { useStructureStore } from '../stores/structureStore'
import { useSelectionStore } from '../stores/selectionStore'
import { selectResiduesInViewer, showSurroundingsAndFocus } from '../lib/molstar-helpers'
import { threeToOne, residueClass, RESIDUE_CLASS_COLORS } from '../lib/residue-codes'
import { ChainSelector } from './ChainSelector'

const RESIDUES_PER_LINE = 60
const BLOCK_SIZE = 10

const CLASS_COLORS = RESIDUE_CLASS_COLORS

const NON_SEQ_COMPS = new Set([
  'HOH', 'WAT', 'DOD', 'H2O',  // water
  'ZN', 'MG', 'CA', 'FE', 'MN', 'CO', 'NI', 'CU', 'NA', 'K',  // ions
  'CL', 'BR', 'SO4', 'PO4', 'NO3', 'CD', 'HG', 'SR', 'BA',
])

function getSequenceChains(allChains: Array<{ id: string; entityId: string; residues: Array<{ seqId: number; authSeqId?: number | null; compId: string; present?: boolean }> }>) {
  return allChains
    .map(chain => ({
      ...chain,
      residues: chain.residues.filter(r => !NON_SEQ_COMPS.has(r.compId)),
    }))
    .filter(chain => chain.residues.length > 1)
    // Drop chains whose residues are all unknown (1-letter code 'X') —
    // typically glycans (NAG / BMA / MAN / ...) and other non-polypeptide
    // chains that snuck into the polymer list with a chain id assigned.
    // The Sequence panel only makes sense for polypeptide / nucleotide
    // chains where threeToOne returns real letters.
    .filter(chain => chain.residues.some(r => threeToOne(r.compId) !== 'X'))
}

export function SequenceViewer({ initialChainId }: { initialChainId?: string } = {}) { // @dsp obj-a1000006
  const allChains = useStructureStore((s) => s.chains)
  const chains = getSequenceChains(allChains)
  const globalChainId = useStructureStore((s) => s.activeChainId)
  const [localChainId, setLocalChainId] = useState<string | null>(initialChainId ?? null)
  // Per-panel toggle: 'structure' shows the PDB auth_seq_id (default);
  // 'order' shows 1-based sequential position within the chain. Selection
  // and 3D-sync continue to use the actual structure seqId either way.
  const [numberingMode, setNumberingMode] = useState<'structure' | 'order'>('structure')
  const scrollRef = useRef<HTMLDivElement>(null)

  // Initialize local chain from global on first load, or when chains change and local is invalid.
  // IMPORTANT: globalChainId comes from the store's UNFILTERED chains[0], which may be a
  // glycan / non-polypeptide chain that's removed by getSequenceChains. So we must validate
  // every candidate (initialChainId, globalChainId) against the filtered list — otherwise the
  // panel silently shows blank and the user has to pick a chain manually.
  useEffect(() => {
    if (chains.length === 0) return
    if (localChainId && chains.find(c => c.id === localChainId)) return
    const candidates = [initialChainId, globalChainId].filter(Boolean) as string[]
    const valid = candidates.find(id => chains.find(c => c.id === id))
    setLocalChainId(valid ?? chains[0].id)
  }, [chains, initialChainId, globalChainId, localChainId])

  const activeChainId = localChainId
  const [dragStart, setDragStart] = useState<number | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  const plugin = useStructureStore((s) => s.plugin)
  const selectedResidues = useSelectionStore((s) => s.selectedResidues)
  const hoveredResidue = useSelectionStore((s) => s.hoveredResidue)
  const toggleSelect = useSelectionStore((s) => s.toggleSelect)
  const selectRange = useSelectionStore((s) => s.selectRange)
  const clearSelection = useSelectionStore((s) => s.clearSelection)
  const hover = useSelectionStore((s) => s.hover)

  const activeChain = chains.find((c) => c.id === activeChainId)

  const handleClear = useCallback(() => {
    clearSelection()
    if (plugin) {
      plugin.managers.interactivity.lociSelects.deselectAll()
    }
  }, [clearSelection, plugin])

  const handleZoom = useCallback(() => {
    if (!plugin || selectedResidues.size === 0) return
    const residues = Array.from(selectedResidues.values())
    selectResiduesInViewer(plugin, residues, 'select')
    // Zoom camera on the PRIMARY viewer only. If the secondary viewer is
    // open and camera sync is on, mirroring would push the primary camera's
    // residue-level zoom onto the secondary viewer (different structure).
    const storeState = useStructureStore.getState()
    const wasSyncEnabled = storeState.cameraSyncEnabled
    const hasSecondary = !!storeState.secondaryPlugin
    if (wasSyncEnabled && hasSecondary) storeState.setCameraSyncEnabled(false)

    // Show selection + 5Å surroundings as sticks AND focus the camera in
    // a single deterministic call (no race with Mol*'s built-in focus
    // auto-pan, which caused the first-click jump).
    showSurroundingsAndFocus(plugin, residues)

    if (wasSyncEnabled && hasSecondary) {
      // Restore sync after the focus animation settles
      setTimeout(() => useStructureStore.getState().setCameraSyncEnabled(true), 500)
    }
  }, [plugin, selectedResidues])

  const handleMouseDown = useCallback((seqId: number) => {
    setDragStart(seqId)
    setIsDragging(false)
  }, [])

  const handleMouseMove = useCallback((seqId: number) => {
    if (dragStart !== null && activeChain) {
      setIsDragging(true)
      // Select range from dragStart to current
      const start = Math.min(dragStart, seqId)
      const end = Math.max(dragStart, seqId)
      const rangeResidues = activeChain.residues
        .filter(r => r.seqId >= start && r.seqId <= end)
        .map(r => ({ chainId: activeChain.id, seqId: r.seqId }))
      selectRange(rangeResidues, 'sequence')
    }
    if (activeChain) {
      hover({ chainId: activeChain.id, seqId }, 'sequence')
    }
  }, [dragStart, activeChain, selectRange, hover])

  const handleMouseUp = useCallback((seqId: number) => {
    if (!isDragging && activeChain) {
      // Simple click, not drag
      toggleSelect({ chainId: activeChain.id, seqId }, 'sequence')
    }
    setDragStart(null)
    setIsDragging(false)
  }, [isDragging, activeChain, toggleSelect])

  const handleMouseLeave = useCallback(() => {
    hover(null, 'sequence')
  }, [hover])

  // Global mouseup to handle drag ending outside the component
  useEffect(() => {
    const handler = () => {
      setDragStart(null)
      setIsDragging(false)
    }
    window.addEventListener('mouseup', handler)
    return () => window.removeEventListener('mouseup', handler)
  }, [])

  // Scroll selected residue into view
  useEffect(() => {
    if (selectedResidues.size === 1 && scrollRef.current) {
      const entry = selectedResidues.values().next().value
      if (entry && entry.chainId === activeChainId) {
        const el = scrollRef.current.querySelector(`[data-seq="${entry.seqId}"]`)
        el?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
      }
    }
  }, [selectedResidues, activeChainId])

  if (chains.length === 0) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>Load a structure to view its sequence</Typography>
      </Box>
    )
  }

  // Split residues into lines
  const residueLines: Array<typeof activeChain extends undefined ? never : NonNullable<typeof activeChain>['residues']> = []
  if (activeChain) {
    for (let i = 0; i < activeChain.residues.length; i += RESIDUES_PER_LINE) {
      residueLines.push(activeChain.residues.slice(i, i + RESIDUES_PER_LINE))
    }
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar */}
      <Box sx={panelToolbarSx}>
        <ChainSelector value={activeChainId} onChange={setLocalChainId} />
        <Tooltip title="Zoom to selected residues in 3D view" placement="bottom">
          <span>
            <IconButton
              aria-label="Zoom to selected residues"
              size="small"
              onClick={handleZoom}
              disabled={selectedResidues.size === 0}
            >
              <ZoomInIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Clear selection (Esc)" placement="bottom">
          <span>
            <IconButton
              aria-label="Clear residue selection"
              size="small"
              onClick={handleClear}
              disabled={selectedResidues.size === 0}
            >
              <ClearIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </span>
        </Tooltip>
        {activeChain && (
          <Typography variant="caption" sx={{ color: 'text.secondary', ml: 0.5 }}>
            {activeChain.residues.length} residues
          </Typography>
        )}
        {selectedResidues.size > 0 && (
          <Typography variant="caption" sx={{ color: 'primary.main', fontWeight: 600 }}>
            · {selectedResidues.size} selected
          </Typography>
        )}
        <Box sx={{ flex: 1 }} />
        <Tooltip title="Numbering: PDB residue ids (structure) vs sequential 1-based position (order)" placement="bottom">
          <span style={{ display: 'inline-flex' }}>
            <ToggleButtonGroup
              size="small"
              value={numberingMode}
              exclusive
              onChange={(_e, v) => { if (v) setNumberingMode(v) }}
              aria-label="Residue numbering mode"
            >
              <ToggleButton value="structure">Structure</ToggleButton>
              <ToggleButton value="order">Sequence</ToggleButton>
            </ToggleButtonGroup>
          </span>
        </Tooltip>
        <Box sx={actionGroupSx}>
          {Object.entries(CLASS_COLORS).filter(([k]) => k !== 'other').map(([label, color]) => (
            <Chip
              key={label}
              label={label}
              size="small"
              sx={{ bgcolor: `${color}20`, color }}
            />
          ))}
        </Box>
      </Box>

      {/* Sequence lines */}
      <Box
        ref={scrollRef}
        onMouseLeave={handleMouseLeave}
        sx={{
          flex: 1,
          overflow: 'auto',
          py: 1, pl: 1, pr: 3,
          userSelect: 'none',
          cursor: dragStart !== null ? 'crosshair' : 'default',
          fontFamily: 'ui-monospace, "Cascadia Mono", Consolas, monospace',
        }}
      >
        {residueLines.map((lineResidues, lineIdx) => {
          // In 'structure' mode show the first residue's PDB author residue
          // number (auth_seq_id — what the structure file literally says,
          // which may start at any number / have insertion gaps). In 'order'
          // mode show the 1-based position within the visible chain (counts
          // ALL residues, including SEQRES-missing ones, so the gutter
          // aligns with the rendered cells). Falls back to seqId when
          // authSeqId isn't available (SEQRES-only residue).
          const orderLineStart = lineIdx * RESIDUES_PER_LINE + 1
          const first = lineResidues[0]
          const lineStart = numberingMode === 'order'
            ? orderLineStart
            : (first?.authSeqId ?? first?.seqId ?? 0)
          return (
            <Box key={lineIdx} sx={{ display: 'flex', alignItems: 'flex-start', mb: 0.5 }}>
              {/* Line number — aligned to residue letters (12px number above + 20px letter) */}
              <Box sx={{
                width: 36, flexShrink: 0, textAlign: 'right', pr: 0.75,
                fontSize: '10px', color: 'text.secondary', fontFamily: 'inherit',
                pt: '12px', lineHeight: '18px',
              }}>
                {lineStart}
              </Box>
              {/* Residues with block spacing */}
              <Box sx={{ display: 'flex', flexWrap: 'nowrap' }}>
                {lineResidues.map((r, rIdx) => {
                  const oneLetterCode = threeToOne(r.compId)
                  const key = `${activeChain!.id}:${r.seqId}`
                  const isSelected = selectedResidues.has(key)
                  const isHovered = hoveredResidue !== null &&
                    hoveredResidue.chainId === activeChain!.id &&
                    hoveredResidue.seqId === r.seqId
                  const rClass = residueClass(oneLetterCode)
                  const baseColor = CLASS_COLORS[rClass] ?? CLASS_COLORS.other
                  // Present === false means the residue is in the SEQRES
                  // block of the PDB but has no atomic coordinates (missing
                  // loop / terminus). Render it grayed-out with a dashed
                  // border so the user can see the gap.
                  const isMissing = r.present === false

                  let bg = 'transparent'
                  let textColor = isMissing ? '#b5bfcc' : baseColor
                  let border = isMissing
                    ? '1px dashed #b5bfcc'
                    : '1px solid transparent'

                  if (isSelected && !isMissing) {
                    bg = '#4a76c4'
                    textColor = '#ffffff'
                    border = '1px solid #4a76c4'
                  } else if (isHovered && !isMissing) {
                    bg = '#e8eaf6'
                    textColor = '#1a1a2e'
                    border = '1px solid #4a76c4'
                  }

                  // Block spacer every BLOCK_SIZE residues
                  const spacer = rIdx > 0 && rIdx % BLOCK_SIZE === 0

                  const showNumber = (rIdx + 1) % BLOCK_SIZE === 0

                  // Fixed width per residue cell — number label constrained to same width
                  const CELL_W = 13

                  return (
                    <span key={r.seqId} style={{
                      display: 'inline-flex',
                      flexDirection: 'column',
                      alignItems: 'center',
                      width: CELL_W,
                      marginLeft: spacer ? 8 : 0,
                    }}>
                      <span style={{
                        fontSize: '7px',
                        color: '#8899aa',
                        height: 11,
                        lineHeight: '11px',
                        fontWeight: 400,
                        textAlign: 'center',
                        overflow: 'visible',
                        whiteSpace: 'nowrap',
                        visibility: showNumber ? 'visible' : 'hidden',
                      }}>
                        {numberingMode === 'order'
                          ? lineIdx * RESIDUES_PER_LINE + rIdx + 1
                          : (r.authSeqId ?? r.seqId)}
                      </span>
                      <Tooltip
                        title={(() => {
                          const orderPos = lineIdx * RESIDUES_PER_LINE + rIdx + 1
                          // Tooltip always shows BOTH numbers — the PDB
                          // author residue number (or fallback) and the
                          // 1-based ordinal position — so the user can
                          // cross-reference regardless of toggle state.
                          const pdb = r.authSeqId ?? r.seqId
                          const numbers = `PDB ${pdb} · #${orderPos}`
                          return isMissing
                            ? `${r.compId} ${numbers} (${rClass}) — declared in SEQRES, missing from structure`
                            : `${r.compId} ${numbers} (${rClass})`
                        })()}
                        placement="top"
                        enterDelay={300}
                      >
                        <span
                          data-seq={r.seqId}
                          onMouseDown={isMissing ? undefined : () => handleMouseDown(r.seqId)}
                          onMouseMove={isMissing ? undefined : () => handleMouseMove(r.seqId)}
                          onMouseUp={isMissing ? undefined : () => handleMouseUp(r.seqId)}
                          style={{
                            display: 'inline-flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            width: CELL_W,
                            height: 18,
                            fontSize: '12px',
                            fontWeight: isMissing ? 400 : 600,
                            fontStyle: isMissing ? 'italic' : 'normal',
                            cursor: isMissing ? 'not-allowed' : 'pointer',
                            backgroundColor: bg,
                            color: textColor,
                            borderRadius: 2,
                            border,
                            transition: 'background-color 50ms',
                          }}
                        >
                          {oneLetterCode}
                        </span>
                      </Tooltip>
                    </span>
                  )
                })}
              </Box>
            </Box>
          )
        })}
      </Box>
    </Box>
  )
}
