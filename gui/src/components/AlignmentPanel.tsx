import { useMemo, useState, useEffect, useCallback, useRef } from 'react'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import FormControl from '@mui/material/FormControl'
import Select from '@mui/material/Select'
import MenuItem from '@mui/material/MenuItem'
import ListSubheader from '@mui/material/ListSubheader'
import Chip from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrong'
import ClearIcon from '@mui/icons-material/Clear'
import { useStructureStore } from '../stores/structureStore'
import { useWorkspaceStore } from '../stores/workspaceStore'
import { workspaceArtifactNameMap } from '../lib/workspace-metadata'
import { threeToOne } from '../lib/residue-codes'
import { alignSequences, chainToSequence } from '../lib/alignment'
import { actionGroupSx, controlSx, panelToolbarSx } from '../ui/layout'
import {
  selectResiduesInViewer,
  clearSelection,
  clearHighlight,
  showSelectionSticks,
  clearSelectionSticks,
  showSurroundingsAndFocus,
} from '../lib/molstar-helpers'

const NON_SEQ = new Set([
  'HOH', 'WAT', 'DOD', 'H2O',
  'ZN', 'MG', 'CA', 'FE', 'MN', 'CO', 'NI', 'CU', 'NA', 'K',
  'CL', 'BR', 'SO4', 'PO4', 'NO3', 'CD', 'HG', 'SR', 'BA',
])

const COL_WIDTH = 12

type ChainSource = 'A' | 'B'
type AlignSide = 'A' | 'B'

interface ChainOption {
  source: ChainSource
  fileName: string
  chainId: string
  /** Display key, unique across structures (source:file:chain) */
  key: string
  /** Polymer-only residues */
  residues: Array<{ seqId: number; compId: string }>
  aaCount: number
}

/**
 * Build column → residue (or null for gap) mapping for one aligned row.
 * Aligned row has length L; residues array has length N <= L.
 */
function buildColumnMap(aligned: string, residues: Array<{ seqId: number; compId: string }>): Array<{ seqId: number; compId: string } | null> {
  const out: Array<{ seqId: number; compId: string } | null> = []
  let ri = 0
  for (let i = 0; i < aligned.length; i++) {
    if (aligned[i] === '-') out.push(null)
    else { out.push(residues[ri] ?? null); ri++ }
  }
  return out
}

export function AlignmentPanel() {
  const primaryChains = useStructureStore((s) => s.chains)
  const secondaryChains = useStructureStore((s) => s.secondaryChains)
  const primaryFile = useStructureStore((s) => s.fileName)
  const secondaryFile = useStructureStore((s) => s.secondaryFileName)
  const primaryPlugin = useStructureStore((s) => s.plugin)
  const secondaryPlugin = useStructureStore((s) => s.secondaryPlugin)
  const alignmentLabelMode = useStructureStore((s) => s.alignmentLabelMode)
  const workspaceArtifacts = useWorkspaceStore((s) => s.active?.artifacts || [])
  const fileNameMap = useMemo(() => workspaceArtifactNameMap(workspaceArtifacts), [workspaceArtifacts])

  // Resolve a source label (file path or metadata name) based on the
  // alignmentLabelMode setting. Falls back to the file path when no name
  // is known (e.g. auto-detected file with no manual metadata yet).
  const labelFor = useCallback((filePath: string): string => {
    if (alignmentLabelMode === 'name') {
      const n = fileNameMap.get(filePath)
      if (n && n.trim()) return n
    }
    return filePath
  }, [alignmentLabelMode, fileNameMap])

  const options = useMemo<ChainOption[]>(() => {
    const out: ChainOption[] = []
    const make = (source: ChainSource, fileName: string | null, chains: typeof primaryChains) => {
      const label = fileName || (source === 'A' ? '(no structure A)' : '(no structure B)')
      const accepted: ChainOption[] = []
      for (const c of chains) {
        const residues = c.residues.filter(r => !NON_SEQ.has(r.compId))
        if (residues.length < 2) continue
        // Drop chains whose residues are all unknown 1-letter codes ('X')
        // — glycans (NAG / BMA / MAN / ...) and other non-polypeptide chains
        // that snuck into the polymer list. Their "sequence" would just be
        // a row of X's, useless for alignment.
        if (!residues.some(r => threeToOne(r.compId) !== 'X')) continue
        accepted.push({
          source, fileName: label, chainId: c.id,
          key: `${source}:${label}:${c.id}`,
          residues, aaCount: residues.length,
        })
      }
      // Sort by chain id so the picker shows A, B, C, ...
      accepted.sort((x, y) => x.chainId.localeCompare(y.chainId, undefined, { numeric: true, sensitivity: 'base' }))
      out.push(...accepted)
    }
    make('A', primaryFile, primaryChains)
    make('B', secondaryFile, secondaryChains)
    return out
  }, [primaryChains, secondaryChains, primaryFile, secondaryFile])

  const [keyA, setKeyA] = useState<string>('')
  const [keyB, setKeyB] = useState<string>('')

  useEffect(() => {
    if (options.length === 0) return
    if (!keyA || !options.find(o => o.key === keyA)) setKeyA(options[0].key)
    if (!keyB || !options.find(o => o.key === keyB)) {
      const aOpt = options.find(o => o.key === (keyA || options[0].key))
      const preferOther = aOpt ? options.find(o => o.source !== aOpt.source) : undefined
      setKeyB((preferOther ?? options[options.length > 1 ? 1 : 0]).key)
    }
  }, [options, keyA, keyB])

  const optA = options.find(o => o.key === keyA)
  const optB = options.find(o => o.key === keyB)

  const alignment = useMemo(() => {
    if (!optA || !optB) return null
    const seqA = chainToSequence(optA.residues)
    const seqB = chainToSequence(optB.residues)
    if (!seqA || !seqB) return null
    return alignSequences(seqA, seqB)
  }, [optA, optB])

  const colMapA = useMemo(
    () => (alignment && optA ? buildColumnMap(alignment.alignedA, optA.residues) : []),
    [alignment, optA]
  )
  const colMapB = useMemo(
    () => (alignment && optB ? buildColumnMap(alignment.alignedB, optB.residues) : []),
    [alignment, optB]
  )

  // Resolve which plugin each side maps to. Source 'A' → primary plugin; 'B' → secondary.
  const pluginA = optA?.source === 'A' ? primaryPlugin : secondaryPlugin
  const pluginB = optB?.source === 'A' ? primaryPlugin : secondaryPlugin

  // Independent per-side selection sets (seqIds in that source chain)
  const [selA, setSelA] = useState<Set<number>>(() => new Set())
  const [selB, setSelB] = useState<Set<number>>(() => new Set())

  // Reset selections when chain choice changes (different source/chain → different residues)
  useEffect(() => { setSelA(new Set()); setSelB(new Set()) }, [keyA, keyB])

  // Reset selections when something fires a global "clear all" (e.g. empty 3D click)
  const clearAllSignal = useStructureStore((s) => s.clearAllSignal)
  useEffect(() => {
    if (clearAllSignal > 0) { setSelA(new Set()); setSelB(new Set()) }
  }, [clearAllSignal])

  // Push side selection → corresponding plugin (cartoon halo + solid sticks)
  const pushToViewer = useCallback(async (side: AlignSide, seqIds: Set<number>) => {
    const plugin = side === 'A' ? pluginA : pluginB
    const opt = side === 'A' ? optA : optB
    if (!plugin || !opt) return
    const residues = Array.from(seqIds).map(seqId => ({ chainId: opt.chainId, seqId }))
    clearSelection(plugin)
    try { await clearSelectionSticks(plugin) } catch {}
    if (residues.length > 0) {
      selectResiduesInViewer(plugin, residues, 'select')
      try { await showSelectionSticks(plugin, residues) } catch {}
    }
  }, [pluginA, pluginB, optA, optB])

  // Drag-select state. We use refs (not state) for the live drag state so
  // updates inside mousemove don't trigger re-renders on every pixel.
  const dragRef = useRef<{ side: AlignSide; anchorCol: number; lastCol: number } | null>(null)
  const isDraggingRef = useRef(false)
  const [hover, setHover] = useState<{ side: AlignSide; col: number } | null>(null)
  const hoverDebounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)

  const colMapForSide = useCallback(
    (side: AlignSide) => (side === 'A' ? colMapA : colMapB),
    [colMapA, colMapB]
  )

  const seqIdsBetween = useCallback((side: AlignSide, fromCol: number, toCol: number): Set<number> => {
    const map = colMapForSide(side)
    const lo = Math.min(fromCol, toCol)
    const hi = Math.max(fromCol, toCol)
    const out = new Set<number>()
    for (let c = lo; c <= hi; c++) {
      const r = map[c]
      if (r) out.add(r.seqId)
    }
    return out
  }, [colMapForSide])

  const handleMouseDown = useCallback((side: AlignSide, col: number) => {
    // Just record the anchor — DO NOT mutate selection here. Mutating selection
    // on mousedown causes a re-render that races with mouseup, dropping clicks
    // and giving "stuck" behaviour.
    dragRef.current = { side, anchorCol: col, lastCol: col }
    isDraggingRef.current = false
  }, [])

  const handleMouseMove = useCallback((side: AlignSide, col: number) => {
    if (!dragRef.current) {
      setHover({ side, col })
      return
    }
    const d = dragRef.current
    if (d.side !== side) return
    if (d.lastCol === col) return
    d.lastCol = col
    isDraggingRef.current = true
    // Local-only update during drag. Mol* is pushed once on mouseup.
    const next = seqIdsBetween(side, d.anchorCol, col)
    if (side === 'A') setSelA(next)
    else setSelB(next)
  }, [seqIdsBetween])

  const handleMouseUp = useCallback((side: AlignSide, col: number) => {
    const d = dragRef.current
    if (!d || d.side !== side) {
      dragRef.current = null
      isDraggingRef.current = false
      return
    }
    if (isDraggingRef.current) {
      // Drag — commit current range
      const next = seqIdsBetween(side, d.anchorCol, col)
      if (side === 'A') setSelA(next)
      else setSelB(next)
      pushToViewer(side, next)
    } else {
      // Plain click — toggle one residue (functional update to avoid stale closure)
      const r = colMapForSide(side)[col]
      if (r) {
        const setSel = side === 'A' ? setSelA : setSelB
        setSel(prev => {
          const next = new Set(prev)
          if (next.has(r.seqId)) next.delete(r.seqId)
          else next.add(r.seqId)
          // Push to viewer outside the updater. Capture `next` and schedule.
          queueMicrotask(() => pushToViewer(side, next))
          return next
        })
      }
    }
    dragRef.current = null
    isDraggingRef.current = false
  }, [seqIdsBetween, pushToViewer, colMapForSide])

  /**
   * Bilateral pick: toggle residues from BOTH sides at the same alignment
   * column.  Used by the number-row click handlers — picking a number ticks
   * residues in both A and B at that column (skipping gap on either side).
   */
  const handleColumnPick = useCallback((col: number) => {
    const rA = colMapA[col]
    const rB = colMapB[col]
    if (rA) {
      setSelA(prev => {
        const next = new Set(prev)
        if (next.has(rA.seqId)) next.delete(rA.seqId)
        else next.add(rA.seqId)
        queueMicrotask(() => pushToViewer('A', next))
        return next
      })
    }
    if (rB) {
      setSelB(prev => {
        const next = new Set(prev)
        if (next.has(rB.seqId)) next.delete(rB.seqId)
        else next.add(rB.seqId)
        queueMicrotask(() => pushToViewer('B', next))
        return next
      })
    }
  }, [colMapA, colMapB, pushToViewer])

  const handleMouseLeave = useCallback(() => {
    setHover(null)
    if (pluginA) clearHighlight(pluginA)
    if (pluginB && pluginB !== pluginA) clearHighlight(pluginB)
  }, [pluginA, pluginB])

  // Hover sync (debounced 50ms; suppressed during drag)
  useEffect(() => {
    clearTimeout(hoverDebounceRef.current)
    if (!hover || dragRef.current) return
    hoverDebounceRef.current = setTimeout(() => {
      const plugin = hover.side === 'A' ? pluginA : pluginB
      const opt = hover.side === 'A' ? optA : optB
      const map = hover.side === 'A' ? colMapA : colMapB
      if (!plugin || !opt) return
      const r = map[hover.col]
      if (!r) { clearHighlight(plugin); return }
      selectResiduesInViewer(plugin, [{ chainId: opt.chainId, seqId: r.seqId }], 'highlight')
    }, 50)
    return () => clearTimeout(hoverDebounceRef.current)
  }, [hover, optA, optB, pluginA, pluginB, colMapA, colMapB])

  // Stop dragging if mouse released anywhere (also commit the current range)
  useEffect(() => {
    const up = () => {
      const d = dragRef.current
      if (d && isDraggingRef.current) {
        const next = seqIdsBetween(d.side, d.anchorCol, d.lastCol)
        if (d.side === 'A') { setSelA(next); pushToViewer('A', next) }
        else { setSelB(next); pushToViewer('B', next) }
      }
      dragRef.current = null
      isDraggingRef.current = false
    }
    window.addEventListener('mouseup', up)
    return () => window.removeEventListener('mouseup', up)
  }, [pushToViewer, seqIdsBetween])

  const cameraSyncEnabled = useStructureStore((s) => s.cameraSyncEnabled)
  const setCameraSyncEnabled = useStructureStore((s) => s.setCameraSyncEnabled)

  // Camera focus: zoom each side's plugin onto its selected residues. When
  // viewer A and viewer B are different plugins AND camera sync is on, the
  // sync would echo viewer A's focus into viewer B and overwrite B's focus.
  // Temporarily suppress sync, do the focus, then restore.
  const handleFocus = useCallback(async () => {
    const needSyncSuppression = pluginA && pluginB && pluginA !== pluginB && cameraSyncEnabled
    if (needSyncSuppression) setCameraSyncEnabled(false)

    // Show selection + neighbors-within-5Å as solid sticks AND zoom the
    // camera, in a single deterministic call. `showSurroundingsAndFocus`
    // uses our own tagged repr instead of focus.setFromLoci, so Mol*'s
    // built-in focus auto-pan doesn't fight our camera move (which caused
    // the first-click jump). The base selection sticks remain from
    // pushToViewer's showSelectionSticks call.
    if (pluginA && optA && selA.size > 0) {
      const residues = Array.from(selA).map(seqId => ({ chainId: optA.chainId, seqId }))
      showSurroundingsAndFocus(pluginA, residues)
    }
    if (pluginB && optB && selB.size > 0 && pluginB !== pluginA) {
      const residues = Array.from(selB).map(seqId => ({ chainId: optB.chainId, seqId }))
      showSurroundingsAndFocus(pluginB, residues)
    }

    if (needSyncSuppression) {
      // Re-enable after both focus animations have settled
      setTimeout(() => setCameraSyncEnabled(true), 500)
    }
  }, [pluginA, pluginB, optA, optB, selA, selB, cameraSyncEnabled, setCameraSyncEnabled])

  const handleClear = useCallback(() => {
    setSelA(new Set())
    setSelB(new Set())
    pushToViewer('A', new Set())
    pushToViewer('B', new Set())
  }, [pushToViewer])

  if (options.length < 1) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', p: 2 }}>
        <Typography variant="caption" sx={{ color: 'text.secondary', textAlign: 'center' }}>
          Load a structure with at least one polymer chain.<br />
          To align across two structures, open a "3D Structure (B)" tab and load a second structure.
        </Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar */}
      <Box sx={panelToolbarSx}>
        <ChainPicker label="A" value={keyA} onChange={setKeyA} options={options} />
        <ChainPicker label="B" value={keyB} onChange={setKeyB} options={options} />

        <Tooltip title="Zoom each viewer to its selection">
          <span style={{ display: 'inline-flex' }}>
            <IconButton aria-label="Focus aligned selections" size="small" onClick={handleFocus} disabled={selA.size === 0 && selB.size === 0}>
              <CenterFocusStrongIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Clear selection (both sides)">
          <span style={{ display: 'inline-flex' }}>
            <IconButton aria-label="Clear alignment selection" size="small" onClick={handleClear} disabled={selA.size === 0 && selB.size === 0}>
              <ClearIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </span>
        </Tooltip>

        {alignment && (
          <Box sx={actionGroupSx}>
            <Chip label={`Identity ${alignment.identity}/${alignment.length} (${((alignment.identity / alignment.length) * 100).toFixed(1)}%)`} size="small" />
            <Chip label={`Similarity ${alignment.similarity}/${alignment.length} (${((alignment.similarity / alignment.length) * 100).toFixed(1)}%)`} size="small" />
            <Chip label={`Score ${alignment.score}`} size="small" />
            {(selA.size > 0 || selB.size > 0) && (
              <Chip label={`Sel A:${selA.size} · B:${selB.size}`} size="small" color="primary" />
            )}
          </Box>
        )}
      </Box>

      {/* Source labels */}
      {optA && optB && (
        <Box sx={{ px: 1, py: 0.5, borderBottom: 1, borderColor: 'divider', display: 'flex', flexDirection: 'column', gap: 0.25 }}>
          <Typography variant="caption" sx={{ fontFamily: 'ui-monospace, monospace', fontSize: '0.65rem' }}>
            <Box component="span" sx={{ color: 'primary.main', fontWeight: 700 }}>A</Box>
            <Box component="span" sx={{ color: 'text.secondary', ml: 0.5 }}>
              {labelFor(optA.fileName)} · chain {optA.chainId} · {optA.aaCount} aa (from {optA.source === 'A' ? 'primary viewer' : 'secondary viewer'})
            </Box>
          </Typography>
          <Typography variant="caption" sx={{ fontFamily: 'ui-monospace, monospace', fontSize: '0.65rem' }}>
            <Box component="span" sx={{ color: 'primary.main', fontWeight: 700 }}>B</Box>
            <Box component="span" sx={{ color: 'text.secondary', ml: 0.5 }}>
              {labelFor(optB.fileName)} · chain {optB.chainId} · {optB.aaCount} aa (from {optB.source === 'A' ? 'primary viewer' : 'secondary viewer'})
            </Box>
          </Typography>
        </Box>
      )}

      {/* Alignment view */}
      <Box
        sx={{
          flex: 1, overflow: 'auto', p: 1,
          fontFamily: 'ui-monospace, Consolas, monospace', fontSize: '12px',
          userSelect: 'none',
          cursor: isDraggingRef.current ? 'crosshair' : 'default',
        }}
        onMouseLeave={handleMouseLeave}
      >
        {!alignment && (
          <Typography variant="caption" sx={{ color: 'text.secondary' }}>
            Select two chains to align (each can come from structure A or B)
          </Typography>
        )}
        {alignment && optA && optB && (
          <AlignmentView
            a={alignment.alignedA}
            b={alignment.alignedB}
            ann={alignment.annotation}
            labelA={`${optA.source}:${optA.chainId}`}
            labelB={`${optB.source}:${optB.chainId}`}
            colMapA={colMapA}
            colMapB={colMapB}
            selA={selA}
            selB={selB}
            hover={hover}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onColumnPick={handleColumnPick}
          />
        )}
      </Box>
    </Box>
  )
}

function ChainPicker({
  label, value, onChange, options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: ChainOption[]
}) {
  const fromA = options.filter(o => o.source === 'A')
  const fromB = options.filter(o => o.source === 'B')
  return (
    <>
      <Typography variant="caption" sx={{ fontWeight: 700, color: 'primary.main' }}>{label}:</Typography>
      <FormControl size="small" sx={controlSx}>
        <Select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          inputProps={{ 'aria-label': `Alignment chain ${label}` }}
        >
          {fromA.length > 0 && (
            <ListSubheader sx={{ fontSize: '0.6rem', lineHeight: '20px', color: 'primary.main', fontWeight: 700 }}>
              Structure A {options.find(o => o.source === 'A')?.fileName ? `· ${options.find(o => o.source === 'A')!.fileName}` : ''}
            </ListSubheader>
          )}
          {fromA.map(o => (
            <MenuItem key={o.key} value={o.key} sx={{ fontSize: '0.7rem', pl: 2 }}>
              Chain {o.chainId} ({o.aaCount} aa)
            </MenuItem>
          ))}
          {fromB.length > 0 && (
            <ListSubheader sx={{ fontSize: '0.6rem', lineHeight: '20px', color: 'primary.main', fontWeight: 700 }}>
              Structure B {options.find(o => o.source === 'B')?.fileName ? `· ${options.find(o => o.source === 'B')!.fileName}` : ''}
            </ListSubheader>
          )}
          {fromB.map(o => (
            <MenuItem key={o.key} value={o.key} sx={{ fontSize: '0.7rem', pl: 2 }}>
              Chain {o.chainId} ({o.aaCount} aa)
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    </>
  )
}

interface AlignmentViewProps {
  a: string
  b: string
  ann: string
  labelA: string
  labelB: string
  colMapA: Array<{ seqId: number; compId: string } | null>
  colMapB: Array<{ seqId: number; compId: string } | null>
  selA: Set<number>
  selB: Set<number>
  hover: { side: AlignSide; col: number } | null
  onMouseDown: (side: AlignSide, col: number) => void
  onMouseMove: (side: AlignSide, col: number) => void
  onMouseUp: (side: AlignSide, col: number) => void
  /** Bilateral toggle: pick residues in BOTH sequences at the column */
  onColumnPick: (col: number) => void
}

function AlignmentView({
  a, b, ann, labelA, labelB,
  colMapA, colMapB, selA, selB, hover,
  onMouseDown, onMouseMove, onMouseUp, onColumnPick,
}: AlignmentViewProps) {
  const LINE = 60
  const rows: Array<{ start: number; aSeg: string; annSeg: string; bSeg: string; aPos: number; bPos: number; aEnd: number; bEnd: number }> = []

  let posA = 0
  let posB = 0
  for (let i = 0; i < a.length; i += LINE) {
    const aSeg = a.slice(i, i + LINE)
    const annSeg = ann.slice(i, i + LINE)
    const bSeg = b.slice(i, i + LINE)
    const aStart = posA + 1
    const bStart = posB + 1
    let aResCount = 0
    let bResCount = 0
    for (const ch of aSeg) if (ch !== '-') aResCount++
    for (const ch of bSeg) if (ch !== '-') bResCount++
    const aEnd = posA + aResCount
    const bEnd = posB + bResCount
    posA = aEnd
    posB = bEnd
    rows.push({ start: i, aSeg, annSeg, bSeg, aPos: aStart, bPos: bStart, aEnd, bEnd })
  }

  // Build the "every 10th residue number" labels for a row, indexed by
  // column position within the LINE. For each column we either show the
  // seqId (if it's at a 10-residue boundary) or nothing.
  function numberLabels(seg: string, segStart: number, colMap: AlignmentViewProps['colMapA'], rowStart: number) {
    const labels: Array<{ col: number; seqId: number | null; show: boolean }> = []
    let residueCounter = segStart - 1
    for (let i = 0; i < seg.length; i++) {
      const col = rowStart + i
      const residue = colMap[col]
      if (residue) {
        residueCounter++
        const show = residueCounter % 10 === 0 || residueCounter === segStart
        labels.push({ col, seqId: residue.seqId, show })
      } else {
        labels.push({ col, seqId: null, show: false })
      }
    }
    return labels
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {rows.map((row, idx) => {
        const labelsA = numberLabels(row.aSeg, row.aPos, colMapA, row.start)
        const labelsB = numberLabels(row.bSeg, row.bPos, colMapB, row.start)
        return (
          <Box key={idx} sx={{ display: 'flex', flexDirection: 'column', gap: 0.25, lineHeight: '15px' }}>
            {/* A numbers row (above A sequence) */}
            <NumberRow
              labels={labelsA}
              side="A"
              selected={selA}
              hover={hover}
              onPick={(_side, col) => onColumnPick(col)}
            />
            {/* A sequence row */}
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <Typography component="span" sx={{ width: 70, color: 'text.secondary', fontSize: '11px', fontFamily: 'inherit', flexShrink: 0 }}>
                {labelA} {row.aPos.toString().padStart(4)}
              </Typography>
              <Box sx={{ display: 'flex', flexWrap: 'nowrap' }}>
                {row.aSeg.split('').map((ch, i) => {
                  const col = row.start + i
                  const residue = colMapA[col]
                  const isSelected = !!residue && selA.has(residue.seqId)
                  const isHovered = hover && hover.side === 'A' && hover.col === col
                  return (
                    <Cell
                      key={i}
                      ch={ch}
                      match={row.annSeg[i]}
                      selected={isSelected}
                      hovered={!!isHovered}
                      title={residue ? `${residue.compId} ${residue.seqId}${row.annSeg[i] === '|' ? ' (identity)' : row.annSeg[i] === ':' ? ' (similar)' : row.annSeg[i] === '.' ? ' (weak)' : ' (mismatch)'}` : 'gap'}
                      onMouseDown={() => onMouseDown('A', col)}
                      onMouseMove={() => onMouseMove('A', col)}
                      onMouseUp={() => onMouseUp('A', col)}
                    />
                  )
                })}
              </Box>
              <Typography component="span" sx={{ ml: 1, color: 'text.secondary', fontSize: '11px', fontFamily: 'inherit' }}>
                {row.aEnd}
              </Typography>
            </Box>
            {/* Match annotation row */}
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <Box sx={{ width: 70, flexShrink: 0 }} />
              <Box sx={{ display: 'flex', flexWrap: 'nowrap' }}>
                {row.annSeg.split('').map((ch, i) => (
                  <span
                    key={i}
                    style={{
                      width: COL_WIDTH, textAlign: 'center', display: 'inline-block',
                      color: ch === '|' ? '#2e7d32' : ch === ':' ? '#5a9a5a' : ch === '.' ? '#8899aa' : 'transparent',
                      fontWeight: 700,
                    }}
                  >
                    {ch}
                  </span>
                ))}
              </Box>
            </Box>
            {/* B sequence row */}
            <Box sx={{ display: 'flex', alignItems: 'center' }}>
              <Typography component="span" sx={{ width: 70, color: 'text.secondary', fontSize: '11px', fontFamily: 'inherit', flexShrink: 0 }}>
                {labelB} {row.bPos.toString().padStart(4)}
              </Typography>
              <Box sx={{ display: 'flex', flexWrap: 'nowrap' }}>
                {row.bSeg.split('').map((ch, i) => {
                  const col = row.start + i
                  const residue = colMapB[col]
                  const isSelected = !!residue && selB.has(residue.seqId)
                  const isHovered = hover && hover.side === 'B' && hover.col === col
                  return (
                    <Cell
                      key={i}
                      ch={ch}
                      match={row.annSeg[i]}
                      selected={isSelected}
                      hovered={!!isHovered}
                      title={residue ? `${residue.compId} ${residue.seqId}${row.annSeg[i] === '|' ? ' (identity)' : row.annSeg[i] === ':' ? ' (similar)' : row.annSeg[i] === '.' ? ' (weak)' : ' (mismatch)'}` : 'gap'}
                      onMouseDown={() => onMouseDown('B', col)}
                      onMouseMove={() => onMouseMove('B', col)}
                      onMouseUp={() => onMouseUp('B', col)}
                    />
                  )
                })}
              </Box>
              <Typography component="span" sx={{ ml: 1, color: 'text.secondary', fontSize: '11px', fontFamily: 'inherit' }}>
                {row.bEnd}
              </Typography>
            </Box>
            {/* B numbers row (below B sequence) */}
            <NumberRow
              labels={labelsB}
              side="B"
              selected={selB}
              hover={hover}
              onPick={(_side, col) => onColumnPick(col)}
            />
          </Box>
        )
      })}
    </Box>
  )
}

function NumberRow({
  labels,
  side,
  selected,
  hover,
  onPick,
}: {
  labels: Array<{ col: number; seqId: number | null; show: boolean }>
  side: AlignSide
  selected: Set<number>
  hover: { side: AlignSide; col: number } | null
  onPick: (side: AlignSide, col: number) => void
}) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center' }}>
      <Box sx={{ width: 70, flexShrink: 0 }} />
      <Box sx={{ display: 'flex', flexWrap: 'nowrap' }}>
        {labels.map((l, i) => {
          const isSelected = l.seqId !== null && selected.has(l.seqId)
          const isHovered = hover && hover.side === side && hover.col === l.col
          const color = isSelected ? '#4a76c4' : isHovered ? '#1a1a2e' : '#8899aa'
          // EVERY cell is clickable — even gaps and blank (non-numbered) cells.
          // onPick → onColumnPick(col), which toggles whatever residues exist
          // at that column on either side (or both). This lets the user click
          // anywhere in the number strip to pick a column.
          return (
            <span
              key={i}
              onClick={() => onPick(side, l.col)}
              title={l.seqId !== null ? `Pick column ${l.col + 1} — toggles both A and B` : 'Pick column — toggles whichever side has a residue here'}
              style={{
                width: COL_WIDTH,
                height: 12,
                fontSize: '8px',
                lineHeight: '12px',
                fontFamily: 'inherit',
                textAlign: 'center',
                color,
                fontWeight: isSelected ? 700 : 500,
                cursor: 'pointer',
                userSelect: 'none',
                overflow: 'visible',
                whiteSpace: 'nowrap',
                // subtle hover background so users see the strip is interactive
                backgroundColor: isHovered ? 'rgba(74,118,196,0.10)' : 'transparent',
                borderRadius: 2,
                transition: 'background-color 60ms',
              }}
            >
              {l.show ? (l.seqId ?? '') : ''}
            </span>
          )
        })}
      </Box>
    </Box>
  )
}

function Cell({
  ch, match, selected, hovered, title,
  onMouseDown, onMouseMove, onMouseUp,
}: {
  ch: string
  match: string
  selected: boolean
  hovered: boolean
  title: string
  onMouseDown: () => void
  onMouseMove: () => void
  onMouseUp: () => void
}) {
  // Base colors by match grade
  let bg = 'transparent'
  let color = '#1a1a2e'
  if (ch === '-') color = '#bfc8d4'
  else if (match === '|') { bg = '#c8e6c9'; color = '#1b5e20' }
  else if (match === ':') { bg = '#fff9c4'; color = '#33691e' }
  else if (match === '.') { bg = '#eceff1'; color = '#37474f' }
  else if (match === ' ' && ch !== '-') { bg = '#ffe0b2'; color = '#bf360c' }

  // Selection overrides
  if (selected) {
    bg = '#4a76c4'
    color = '#ffffff'
  } else if (hovered) {
    bg = '#e8eaf6'
    color = '#1a1a2e'
  }

  return (
    <Tooltip title={title} enterDelay={400}>
      <span
        onMouseDown={(e) => { e.preventDefault(); onMouseDown() }}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        style={{
          width: COL_WIDTH,
          textAlign: 'center',
          display: 'inline-block',
          backgroundColor: bg,
          color,
          fontWeight: 600,
          borderRadius: 2,
          cursor: ch === '-' ? 'default' : 'pointer',
          border: selected ? '1px solid #4a76c4' : '1px solid transparent',
        }}
      >
        {ch}
      </span>
    </Tooltip>
  )
}
