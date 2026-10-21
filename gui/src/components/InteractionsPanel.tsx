import { useState, useEffect, useCallback } from 'react'
import Box from '@mui/material/Box'
import { controlWrapperSx, panelToolbarSx } from '../ui/layout'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import IconButton from '@mui/material/IconButton'
import RefreshIcon from '@mui/icons-material/Refresh'
import CenterFocusStrongIcon from '@mui/icons-material/CenterFocusStrong'
import HubIcon from '@mui/icons-material/Hub'
import Tooltip from '@mui/material/Tooltip'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableContainer from '@mui/material/TableContainer'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import FormControl from '@mui/material/FormControl'
import Select from '@mui/material/Select'
import MenuItem from '@mui/material/MenuItem'
import { useStructureStore } from '../stores/structureStore'
import { selectResiduesInViewer, focusResiduesInViewer } from '../lib/molstar-helpers'
import { toCanonicalThree } from '../lib/residue-codes'
import { computeInteractions } from 'molstar/lib/mol-model-props/computed/interactions/interactions'
import { InteractionType, interactionTypeLabel } from 'molstar/lib/mol-model-props/computed/interactions/common'
import { StructureProperties as SP, StructureElement } from 'molstar/lib/mol-model/structure'
import { BondType } from 'molstar/lib/mol-model/structure/model/types'
import { SyncRuntimeContext } from 'molstar/lib/mol-task/execution/synchronous'

// Custom types for covalent bonds (negative to avoid collision with InteractionType enum)
const CUSTOM_DISULFIDE = -1
const CUSTOM_COVALENT = -2

interface InteractionRow {
  type: number // InteractionType or custom negative
  typeLabel: string
  chainA: string
  resA: string
  seqIdA: number
  chainB: string
  resB: string
  seqIdB: number
}

function getTypeLabel(type: number): string {
  if (type === CUSTOM_DISULFIDE) return 'Disulfide Bridge'
  if (type === CUSTOM_COVALENT) return 'Covalent Bond'
  return interactionTypeLabel(type as InteractionType)
}

const TYPE_COLORS: Record<number, string> = {
  [InteractionType.HydrogenBond]: '#2e7d32',
  [InteractionType.WeakHydrogenBond]: '#66bb6a',
  [InteractionType.Ionic]: '#c62828',
  [InteractionType.CationPi]: '#7b1fa2',
  [InteractionType.PiStacking]: '#6a1b9a',
  [InteractionType.HalogenBond]: '#e68a00',
  [InteractionType.Hydrophobic]: '#1565c0',
  [InteractionType.MetalCoordination]: '#5d4037',
  [InteractionType.Unknown]: '#5a607a',
  [CUSTOM_DISULFIDE]: '#b8860b',
  [CUSTOM_COVALENT]: '#555555',
}

const WATER_COMPS = new Set(['HOH', 'WAT', 'DOD', 'H2O'])

export function InteractionsPanel() {
  const plugin = useStructureStore((s) => s.plugin)
  const fileName = useStructureStore((s) => s.fileName)
  const focusedChainId = useStructureStore((s) => s.focusedChainId)
  const focusedCategory = useStructureStore((s) => s.focusedCategory)
  const setFocusedChain = useStructureStore((s) => s.setFocusedChain)
  const [rows, setRows] = useState<InteractionRow[]>([])
  const [loading, setLoading] = useState(false)
  const [chainPairA, setChainPairA] = useState<string>('') // '' = any
  const [chainPairB, setChainPairB] = useState<string>('') // '' = any
  const [filters, setFilters] = useState<Set<number>>(new Set([
    InteractionType.HydrogenBond,
    InteractionType.Ionic,
    InteractionType.CationPi,
    InteractionType.PiStacking,
    InteractionType.HalogenBond,
    InteractionType.Hydrophobic,
    InteractionType.MetalCoordination,
    CUSTOM_DISULFIDE,
    CUSTOM_COVALENT,
  ]))

  const compute = useCallback(async () => {
    if (!plugin) return
    const structures = plugin.managers.structure.hierarchy.current.structures
    if (structures.length === 0) return

    const structure = structures[0].cell.obj?.data
    if (!structure) return

    setLoading(true)
    try {
      const interactions = await computeInteractions(
        { runtime: SyncRuntimeContext, assetManager: plugin.managers.asset },
        structure,
        {} as any
      )

      const results: InteractionRow[] = []
      const locA = StructureElement.Location.create(structure)
      const locB = StructureElement.Location.create(structure)

      const getUnit = (id: number) => structure.unitMap.get(id)

      // Inter-unit contacts
      for (const edge of interactions.contacts.edges) {
        const type = edge.props.type
        if (type === InteractionType.Unknown) continue

        const unitA = getUnit(edge.unitA)
        const unitB = getUnit(edge.unitB)
        if (!unitA || !unitB) continue

        const fA = interactions.unitsFeatures.get(edge.unitA)
        const fB = interactions.unitsFeatures.get(edge.unitB)
        if (!fA || !fB) continue

        const memberA = fA.members[fA.offsets[edge.indexA]]
        const memberB = fB.members[fB.offsets[edge.indexB]]
        if (memberA === undefined || memberB === undefined) continue

        locA.unit = unitA
        locA.element = unitA.elements[memberA]
        locB.unit = unitB
        locB.element = unitB.elements[memberB]

        const compA = SP.atom.label_comp_id(locA)
        const compB = SP.atom.label_comp_id(locB)
        if (WATER_COMPS.has(compA) || WATER_COMPS.has(compB)) continue

        results.push({
          type,
          typeLabel: getTypeLabel(type),
          chainA: SP.chain.label_asym_id(locA),
          resA: toCanonicalThree(compA),
          seqIdA: SP.residue.label_seq_id(locA),
          chainB: SP.chain.label_asym_id(locB),
          resB: toCanonicalThree(compB),
          seqIdB: SP.residue.label_seq_id(locB),
        })
      }

      // Intra-unit contacts
      for (const unitId of interactions.unitsContacts.keys()) {
        const contacts = interactions.unitsContacts.get(unitId)
        const unit = getUnit(unitId)
        if (!unit || !contacts) continue
        const features = interactions.unitsFeatures.get(unitId)
        if (!features) continue

        const { a, b, edgeProps } = contacts
        for (let i = 0; i < a.length; i++) {
          const type = edgeProps.type[i]
          if (type === InteractionType.Unknown) continue

          const memberA = features.members[features.offsets[a[i]]]
          const memberB = features.members[features.offsets[b[i]]]
          if (memberA === undefined || memberB === undefined) continue

          locA.unit = unit
          locA.element = unit.elements[memberA]
          locB.unit = unit
          locB.element = unit.elements[memberB]

          const compA = SP.atom.label_comp_id(locA)
          const compB = SP.atom.label_comp_id(locB)
          if (WATER_COMPS.has(compA) || WATER_COMPS.has(compB)) continue

          const chainA = SP.chain.label_asym_id(locA)
          const chainB = SP.chain.label_asym_id(locB)
          const seqA = SP.residue.label_seq_id(locA)
          const seqB = SP.residue.label_seq_id(locB)
          if (seqA === seqB && chainA === chainB) continue

          results.push({
            type,
            typeLabel: getTypeLabel(type),
            chainA, resA: toCanonicalThree(compA), seqIdA: seqA,
            chainB, resB: toCanonicalThree(compB), seqIdB: seqB,
          })
        }
      }

      // Helper: detect disulfide by flag OR by atom names (SG-SG in CYS-like residues)
      const CYS_COMPS = new Set(['CYS', 'CYX', 'CYM', 'CYF', 'CSS', 'CSO', 'OCS', 'CME', 'CSD', 'CSW', 'CSX'])

      function isDisulfideBond(
        flagOrFlags: number,
        locA: StructureElement.Location,
        locB: StructureElement.Location,
      ): boolean {
        // Check explicit flag first
        if (BondType.is(flagOrFlags as BondType, BondType.Flag.Disulfide)) return true
        // Heuristic: SG–SG bond between cysteine-like residues
        const atomA = SP.atom.label_atom_id(locA)
        const atomB = SP.atom.label_atom_id(locB)
        if (atomA === 'SG' && atomB === 'SG') {
          const compA = SP.atom.label_comp_id(locA)
          const compB = SP.atom.label_comp_id(locB)
          if (CYS_COMPS.has(compA) && CYS_COMPS.has(compB)) return true
        }
        return false
      }

      // Extract covalent bonds — inter-unit (between different units/chains)
      const interBonds = structure.interUnitBonds
      for (const edge of interBonds.edges) {
        const flag = edge.props.flag
        const isCovalent = BondType.is(flag as BondType, BondType.Flag.Covalent)
        const hasDisulfideFlag = BondType.is(flag as BondType, BondType.Flag.Disulfide)

        if (!isCovalent && !hasDisulfideFlag) continue

        const unitA = structure.unitMap.get(edge.unitA)
        const unitB = structure.unitMap.get(edge.unitB)
        if (!unitA || !unitB) continue

        locA.unit = unitA
        locA.element = unitA.elements[edge.indexA]
        locB.unit = unitB
        locB.element = unitB.elements[edge.indexB]

        const compA = SP.atom.label_comp_id(locA)
        const compB = SP.atom.label_comp_id(locB)
        if (WATER_COMPS.has(compA) || WATER_COMPS.has(compB)) continue

        const chainA = SP.chain.label_asym_id(locA)
        const chainB = SP.chain.label_asym_id(locB)
        const seqA = SP.residue.label_seq_id(locA)
        const seqB = SP.residue.label_seq_id(locB)

        if (seqA === seqB && chainA === chainB) continue

        const isDisulfide = isDisulfideBond(flag, locA, locB)
        const type = isDisulfide ? CUSTOM_DISULFIDE : CUSTOM_COVALENT
        results.push({
          type,
          typeLabel: getTypeLabel(type),
          chainA, resA: toCanonicalThree(compA), seqIdA: seqA,
          chainB, resB: toCanonicalThree(compB), seqIdB: seqB,
        })
      }

      // Extract covalent bonds — intra-unit (within same unit, e.g. same-chain disulfides)
      for (const unit of structure.units) {
        if (unit.kind !== 0 /* Unit.Kind.Atomic */) continue
        const bonds = (unit as any).bonds
        const { a, b, edgeProps: { flags } } = bonds
        locA.unit = unit
        locB.unit = unit

        for (let i = 0; i < a.length; i++) {
          const flag = flags[i]
          locA.element = unit.elements[a[i]]
          locB.element = unit.elements[b[i]]

          const isDisulfide = isDisulfideBond(flag, locA, locB)
          if (!isDisulfide) continue // Only disulfides from intra-unit (skip backbone covalent)

          const compA = SP.atom.label_comp_id(locA)
          const compB = SP.atom.label_comp_id(locB)
          if (WATER_COMPS.has(compA) || WATER_COMPS.has(compB)) continue

          const chainA = SP.chain.label_asym_id(locA)
          const chainB = SP.chain.label_asym_id(locB)
          const seqA = SP.residue.label_seq_id(locA)
          const seqB = SP.residue.label_seq_id(locB)

          if (seqA === seqB && chainA === chainB) continue

          results.push({
            type: CUSTOM_DISULFIDE,
            typeLabel: getTypeLabel(CUSTOM_DISULFIDE),
            chainA, resA: toCanonicalThree(compA), seqIdA: seqA,
            chainB, resB: toCanonicalThree(compB), seqIdB: seqB,
          })
        }
      }

      // Deduplicate
      const seen = new Set<string>()
      const deduped = results.filter(r => {
        const k1 = `${r.type}:${r.chainA}${r.seqIdA}-${r.chainB}${r.seqIdB}`
        const k2 = `${r.type}:${r.chainB}${r.seqIdB}-${r.chainA}${r.seqIdA}`
        if (seen.has(k1) || seen.has(k2)) return false
        seen.add(k1)
        return true
      })

      deduped.sort((a, b) => a.type - b.type || a.chainA.localeCompare(b.chainA) || a.seqIdA - b.seqIdA)
      setRows(deduped)
    } catch (e: any) {
      console.error('Interactions computation failed:', e)
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [plugin])

  useEffect(() => {
    if (fileName) compute()
    else setRows([])
  }, [fileName, compute])

  const toggleFilter = useCallback((type: number) => {
    setFilters(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }, [])

  const focusInteraction = useCallback((row: InteractionRow) => {
    if (!plugin) return
    const residues = [
      { chainId: row.chainA, seqId: row.seqIdA },
      { chainId: row.chainB, seqId: row.seqIdB },
    ]
    plugin.managers.interactivity.lociSelects.deselectAll()
    selectResiduesInViewer(plugin, residues, 'select')
    focusResiduesInViewer(plugin, residues)
    // Zoom camera to selection
    const structure = plugin.managers.structure.hierarchy.current.structures[0]?.cell.obj?.data
    if (structure) {
      const loci = plugin.managers.structure.selection.getLoci(structure)
      if (loci) plugin.managers.camera.focusLoci(loci)
    }
  }, [plugin])

  // Collect all chains
  const allChains = new Set<string>()
  for (const r of rows) {
    allChains.add(r.chainA)
    allChains.add(r.chainB)
  }
  const sortedChains = Array.from(allChains).sort()

  const filteredRows = rows.filter(r => {
    if (!filters.has(r.type)) return false
    if (chainPairA || chainPairB) {
      const a = chainPairA || null
      const b = chainPairB || null
      const matchForward = (!a || r.chainA === a) && (!b || r.chainB === b)
      const matchReverse = (!a || r.chainB === a) && (!b || r.chainA === b)
      if (!matchForward && !matchReverse) return false
    }
    if (focusedChainId && r.chainA !== focusedChainId && r.chainB !== focusedChainId) {
      return false
    }
    return true
  })

  // Per-partner contact counts when an interface is focused
  const partnerCounts = (() => {
    if (!focusedChainId) return null
    const counts = new Map<string, number>()
    for (const r of rows) {
      if (r.chainA === focusedChainId && r.chainB !== focusedChainId) {
        counts.set(r.chainB, (counts.get(r.chainB) ?? 0) + 1)
      } else if (r.chainB === focusedChainId && r.chainA !== focusedChainId) {
        counts.set(r.chainA, (counts.get(r.chainA) ?? 0) + 1)
      }
    }
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])
  })()

  const focusAllFiltered = useCallback(() => {
    if (!plugin || filteredRows.length === 0) return
    const seen = new Set<string>()
    const residues: Array<{ chainId: string; seqId: number }> = []
    for (const r of filteredRows) {
      const kA = `${r.chainA}:${r.seqIdA}`
      const kB = `${r.chainB}:${r.seqIdB}`
      if (!seen.has(kA)) { seen.add(kA); residues.push({ chainId: r.chainA, seqId: r.seqIdA }) }
      if (!seen.has(kB)) { seen.add(kB); residues.push({ chainId: r.chainB, seqId: r.seqIdB }) }
    }
    plugin.managers.interactivity.lociSelects.deselectAll()
    selectResiduesInViewer(plugin, residues, 'select')
    focusResiduesInViewer(plugin, residues)
    const structure = plugin.managers.structure.hierarchy.current.structures[0]?.cell.obj?.data
    if (structure) {
      const loci = plugin.managers.structure.selection.getLoci(structure)
      if (loci) plugin.managers.camera.focusLoci(loci)
    }
  }, [plugin, filteredRows])

  const typeCounts = new Map<number, number>()
  for (const r of rows) {
    typeCounts.set(r.type, (typeCounts.get(r.type) ?? 0) + 1)
  }

  if (!fileName) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>Load a structure to see interactions</Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Box sx={panelToolbarSx}>
        <Tooltip title="Recompute interactions">
          <Box component="span" sx={controlWrapperSx}>
            <IconButton aria-label="Recompute interactions" size="small" onClick={compute} disabled={loading}>
              <RefreshIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </Box>
        </Tooltip>
        <Tooltip title="Select all interaction residues and zoom">
          <Box component="span" sx={controlWrapperSx}>
            <IconButton aria-label="Focus interaction residues" size="small" onClick={focusAllFiltered} disabled={filteredRows.length === 0}>
              <CenterFocusStrongIcon sx={{ fontSize: 14 }} />
            </IconButton>
          </Box>
        </Tooltip>
        {loading && <CircularProgress size={12} />}
        {Array.from(typeCounts.entries()).map(([type, count]) => (
          <Chip
            key={type}
            label={`${getTypeLabel(type)} (${count})`}
            size="small"
            onClick={() => toggleFilter(type)}
            sx={{
              fontWeight: 600,
              bgcolor: filters.has(type) ? `${TYPE_COLORS[type] ?? '#5a607a'}25` : 'transparent',
              color: filters.has(type) ? TYPE_COLORS[type] ?? '#5a607a' : 'text.secondary',
              border: '1px solid',
              borderColor: filters.has(type) ? TYPE_COLORS[type] ?? '#5a607a' : 'divider',
              cursor: 'pointer',
              '& .MuiChip-label': { px: 0.5 },
            }}
          />
        ))}
        {sortedChains.length > 1 && (
          <>
            <Box sx={{ width: '1px', height: 14, bgcolor: 'divider', mx: 0.25 }} />
            <FormControl size="small" sx={{ minWidth: 60 }}>
              <Select
                value={chainPairA}
                onChange={(e) => setChainPairA(e.target.value)}
                displayEmpty
                inputProps={{ 'aria-label': 'First interaction chain' }}
              >
                <MenuItem value="" sx={{ fontSize: '0.7rem' }}>Any</MenuItem>
                {sortedChains.map(c => (
                  <MenuItem key={c} value={c} sx={{ fontSize: '0.7rem' }}>Chain {c}</MenuItem>
                ))}
              </Select>
            </FormControl>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.6rem' }}>↔</Typography>
            <FormControl size="small" sx={{ minWidth: 60 }}>
              <Select
                value={chainPairB}
                onChange={(e) => setChainPairB(e.target.value)}
                displayEmpty
                inputProps={{ 'aria-label': 'Second interaction chain' }}
              >
                <MenuItem value="" sx={{ fontSize: '0.7rem' }}>Any</MenuItem>
                {sortedChains.map(c => (
                  <MenuItem key={c} value={c} sx={{ fontSize: '0.7rem' }}>Chain {c}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </>
        )}
      </Box>

      {focusedChainId && partnerCounts && (
        <Box sx={{
          px: 1, py: 0.5, borderBottom: 1, borderColor: 'divider',
          display: 'flex', alignItems: 'center', gap: 0.75, flexWrap: 'wrap',
          bgcolor: 'action.hover',
        }}>
          <HubIcon sx={{ fontSize: 14, color: 'primary.main' }} />
          <Typography variant="caption" sx={{ fontWeight: 700, fontSize: '0.7rem' }}>
            Interface: {focusedCategory ? `${focusedCategory} ` : ''}chain {focusedChainId}
          </Typography>
          <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem' }}>
            · {filteredRows.length} contact{filteredRows.length !== 1 ? 's' : ''}
          </Typography>
          {partnerCounts.length > 0 && (
            <>
              <Box sx={{ width: '1px', height: 12, bgcolor: 'divider', mx: 0.25 }} />
              {partnerCounts.map(([partner, count]) => (
                <Chip
                  key={partner}
                  label={`↔ ${partner} (${count})`}
                  size="small"
                  sx={{ fontWeight: 600 }}
                />
              ))}
            </>
          )}
          <Box sx={{ flex: 1 }} />
          <Typography
            component="span"
            variant="caption"
            onClick={() => setFocusedChain(null)}
            sx={{
              cursor: 'pointer', fontSize: '0.65rem', color: 'primary.main',
              textDecoration: 'underline', '&:hover': { opacity: 0.7 },
            }}
          >
            Clear
          </Typography>
        </Box>
      )}

      <TableContainer sx={{ flex: 1 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell>Type</TableCell>
              <TableCell>Residue A</TableCell>
              <TableCell>Residue B</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {filteredRows.map((r, i) => (
              <TableRow key={i} hover sx={{ cursor: 'pointer' }} onClick={() => focusInteraction(r)}>
                <TableCell>
                  <Chip
                    label={r.typeLabel}
                    size="small"
                    sx={{
                      height: 18,
                      fontSize: '0.5rem',
                      fontWeight: 600,
                      bgcolor: `${TYPE_COLORS[r.type] ?? '#5a607a'}20`,
                      color: TYPE_COLORS[r.type] ?? '#5a607a',
                      '& .MuiChip-label': { px: 0.5 },
                    }}
                  />
                </TableCell>
                <TableCell>
                  <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: '0.7rem' }}>
                    {r.chainA}:{r.resA}{r.seqIdA}
                  </Typography>
                </TableCell>
                <TableCell>
                  <Typography variant="caption" sx={{ fontFamily: 'monospace', fontSize: '0.7rem' }}>
                    {r.chainB}:{r.resB}{r.seqIdB}
                  </Typography>
                </TableCell>
              </TableRow>
            ))}
            {!loading && filteredRows.length === 0 && (
              <TableRow>
                <TableCell colSpan={3}>
                  <Typography variant="caption" sx={{ color: 'text.secondary' }}>
                    {rows.length === 0 ? 'No interactions found' : 'No interactions match filters'}
                  </Typography>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <Box sx={{ px: 1, py: 0.5, borderTop: 1, borderColor: 'divider' }}>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          {filteredRows.length} of {rows.length} interactions (water excluded)
        </Typography>
      </Box>
    </Box>
  )
}
