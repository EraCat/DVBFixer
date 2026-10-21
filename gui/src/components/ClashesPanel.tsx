import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import Button from '@mui/material/Button'
import Table from '@mui/material/Table'
import TableBody from '@mui/material/TableBody'
import TableCell from '@mui/material/TableCell'
import TableContainer from '@mui/material/TableContainer'
import TableHead from '@mui/material/TableHead'
import TableRow from '@mui/material/TableRow'
import TextField from '@mui/material/TextField'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import RefreshIcon from '@mui/icons-material/Refresh'
import ClearIcon from '@mui/icons-material/Clear'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ChevronRightIcon from '@mui/icons-material/ChevronRight'
import { useStructureStore } from '../stores/structureStore'
import { computeClashes, type Clash } from '../lib/clash-detection'
import { showClashAndFocus, clearClashSticks } from '../lib/molstar-helpers'
import { compactIconButtonSx, panelToolbarSx } from '../ui/layout'

type SeverityFilter = 'all' | 'bad' | 'severe'

interface ClashGroup {
  key: string
  chainA: string
  resIdA: number
  resNameA: string
  chainB: string
  resIdB: number
  resNameB: string
  clashes: Clash[]              // sorted by overlap desc
  worstOverlap: number
  worstSeverity: 'bad' | 'severe'
  severeCount: number
  badCount: number
}

/** Canonical (chain,resId) ordering so A↔B == B↔A maps to one group. */
function groupKey(c: Clash): { key: string; first: 'a' | 'b' } {
  const a = `${c.chainA}:${c.resIdA}`
  const b = `${c.chainB}:${c.resIdB}`
  return a <= b
    ? { key: `${a}|${b}`, first: 'a' }
    : { key: `${b}|${a}`, first: 'b' }
}

export function ClashesPanel() {
  const plugin = useStructureStore((s) => s.plugin)
  const fileName = useStructureStore((s) => s.fileName)
  const [clashes, setClashes] = useState<Clash[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [minOverlap, setMinOverlap] = useState(0.4)
  const [severity, setSeverity] = useState<SeverityFilter>('all')
  /** Id of the row most recently clicked — kept highlighted until another
   *  row is clicked or Reset is pressed. Matches the user's "highlight
   *  last one" requirement. */
  const [activeId, setActiveId] = useState<string | null>(null)
  const [groupByResidue, setGroupByResidue] = useState(false)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  const compute = useCallback(async () => {
    if (!plugin) return
    setLoading(true)
    setError(null)
    try {
      // Compute is synchronous + pure; wrap in await Promise.resolve so
      // the spinner has a chance to render on large structures.
      await Promise.resolve()
      const result = computeClashes(plugin, { minOverlap })
      setClashes(result)
    } catch (e: any) {
      setError(e?.message ?? String(e))
      setClashes([])
    } finally {
      setLoading(false)
    }
  }, [plugin, minOverlap])

  // Recompute on structure load and whenever minOverlap changes.
  useEffect(() => {
    if (fileName) compute()
    else setClashes([])
  }, [fileName, compute])

  const filtered = useMemo(() => {
    if (severity === 'all') return clashes
    return clashes.filter(c => c.severity === severity)
  }, [clashes, severity])

  const counts = useMemo(() => {
    let bad = 0, severe = 0
    for (const c of clashes) {
      if (c.severity === 'severe') severe++
      else bad++
    }
    return { bad, severe }
  }, [clashes])

  /** Group filtered clashes by canonical residue pair. Each group's
   *  endpoints are aligned to the first clash's orientation so the
   *  table consistently shows the same A/B sides per group. */
  const groups = useMemo<ClashGroup[]>(() => {
    const byKey = new Map<string, ClashGroup>()
    for (const c of filtered) {
      const { key, first } = groupKey(c)
      let g = byKey.get(key)
      if (!g) {
        const a = first === 'a'
          ? { chainId: c.chainA, resId: c.resIdA, resName: c.resNameA }
          : { chainId: c.chainB, resId: c.resIdB, resName: c.resNameB }
        const b = first === 'a'
          ? { chainId: c.chainB, resId: c.resIdB, resName: c.resNameB }
          : { chainId: c.chainA, resId: c.resIdA, resName: c.resNameA }
        g = {
          key,
          chainA: a.chainId, resIdA: a.resId, resNameA: a.resName,
          chainB: b.chainId, resIdB: b.resId, resNameB: b.resName,
          clashes: [], worstOverlap: 0, worstSeverity: 'bad',
          severeCount: 0, badCount: 0,
        }
        byKey.set(key, g)
      }
      g.clashes.push(c)
      if (c.overlap > g.worstOverlap) g.worstOverlap = c.overlap
      if (c.severity === 'severe') { g.severeCount++; g.worstSeverity = 'severe' }
      else g.badCount++
    }
    const out = Array.from(byKey.values())
    for (const g of out) g.clashes.sort((x, y) => y.overlap - x.overlap)
    out.sort((x, y) => y.worstOverlap - x.worstOverlap)
    return out
  }, [filtered])

  const handleRowClick = useCallback((clash: Clash) => {
    if (!plugin) return
    setActiveId(clash.id)
    showClashAndFocus(plugin, {
      a: { chainId: clash.chainA, seqId: clash.resIdA, atomName: clash.atomA },
      b: { chainId: clash.chainB, seqId: clash.resIdB, atomName: clash.atomB },
      severity: clash.severity,
    })
  }, [plugin])

  const handleGroupClick = useCallback((group: ClashGroup) => {
    // Focus the WORST atom-pair in the group so the user immediately sees
    // the most problematic geometry; the group row stays selected
    // because activeId.parent is computed from the group's clashes.
    if (group.clashes.length === 0) return
    handleRowClick(group.clashes[0])
  }, [handleRowClick])

  const toggleExpanded = useCallback((key: string) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  const handleClearHighlight = useCallback(() => {
    setActiveId(null)
    if (plugin) clearClashSticks(plugin).catch(() => {})
  }, [plugin])

  if (!fileName) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>
          Load a structure to detect clashes
        </Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: 0, overflow: 'hidden' }}>
      {/* Header */}
      <Box sx={panelToolbarSx}>
        <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.secondary', textTransform: 'uppercase', letterSpacing: 1 }}>
          Clashes
        </Typography>
        <Chip
          label={`${counts.bad} bad`}
          size="small"
          color={counts.bad > 0 ? 'warning' : 'default'}
          variant="outlined"
        />
        <Chip
          label={`${counts.severe} severe`}
          size="small"
          color={counts.severe > 0 ? 'error' : 'default'}
          variant="outlined"
        />

        <Box sx={{ flex: 1 }} />

        <ToggleButtonGroup
          size="small"
          exclusive
          value={severity}
          onChange={(_e, v: SeverityFilter | null) => v && setSeverity(v)}
          aria-label="Clash severity filter"
        >
          <ToggleButton value="all">All</ToggleButton>
          <ToggleButton value="bad">Bad</ToggleButton>
          <ToggleButton value="severe">Severe</ToggleButton>
        </ToggleButtonGroup>

        <Tooltip title="Group clashes by residue pair">
          <ToggleButton
            value="group"
            size="small"
            selected={groupByResidue}
            onChange={() => setGroupByResidue(g => !g)}
          >
            Group
          </ToggleButton>
        </Tooltip>

        <Tooltip title="Minimum VdW overlap to report (Å)">
          <TextField
            size="small"
            type="number"
            value={minOverlap}
            onChange={(e) => {
              const v = parseFloat(e.target.value)
              if (Number.isFinite(v) && v >= 0) setMinOverlap(v)
            }}
            sx={{ width: 80 }}
            slotProps={{ htmlInput: { step: 0.1, min: 0, 'aria-label': 'Minimum overlap in Å' } }}
          />
        </Tooltip>

        <Tooltip title="Clear highlight">
          <span>
            <IconButton aria-label="Clear clash highlight" size="small" onClick={handleClearHighlight} disabled={!activeId}>
              <ClearIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </span>
        </Tooltip>
        <Tooltip title="Recompute">
          <IconButton aria-label="Recompute clashes" size="small" onClick={compute}>
            <RefreshIcon sx={{ fontSize: 16 }} />
          </IconButton>
        </Tooltip>
      </Box>

      {error && (
        <Box sx={{ px: 1.5, py: 0.5, color: 'error.main', fontSize: '0.75rem' }}>{error}</Box>
      )}

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 2 }}>
          <CircularProgress size={20} />
        </Box>
      )}

      {!loading && clashes.length === 0 && (
        <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', flex: 1, gap: 1, p: 2 }}>
          <Typography variant="caption" sx={{ color: 'success.main' }}>
            No clashes above {minOverlap.toFixed(1)} Å overlap — structure looks clean.
          </Typography>
          <Button size="small" onClick={compute}>Recompute</Button>
        </Box>
      )}

      {!loading && filtered.length === 0 && clashes.length > 0 && (
        <Box sx={{ p: 2, textAlign: 'center', color: 'text.secondary', fontSize: '0.75rem' }}>
          No clashes match the current filter.
        </Box>
      )}

      {!loading && filtered.length > 0 && (
        <TableContainer sx={{ flex: 1, minHeight: 0 }}>
          <Table size="small" stickyHeader>
            <TableHead>
              <TableRow>
                {groupByResidue && (
                  <TableCell sx={{ fontSize: '0.65rem', fontWeight: 700, py: 0.5, width: 28, p: 0 }} />
                )}
                <TableCell sx={{ fontSize: '0.65rem', fontWeight: 700, py: 0.5 }}>Severity</TableCell>
                <TableCell sx={{ fontSize: '0.65rem', fontWeight: 700, py: 0.5 }}>
                  {groupByResidue ? 'Worst (Å)' : 'Overlap (Å)'}
                </TableCell>
                <TableCell sx={{ fontSize: '0.65rem', fontWeight: 700, py: 0.5 }}>Distance (Å)</TableCell>
                <TableCell sx={{ fontSize: '0.65rem', fontWeight: 700, py: 0.5 }}>
                  {groupByResidue ? 'Residue A' : 'Atom A'}
                </TableCell>
                <TableCell sx={{ fontSize: '0.65rem', fontWeight: 700, py: 0.5 }}>
                  {groupByResidue ? 'Residue B' : 'Atom B'}
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {!groupByResidue && filtered.map(c => {
                const isActive = activeId === c.id
                const sevColor = c.severity === 'severe' ? '#c62828' : '#e68a00'
                return (
                  <TableRow
                    key={c.id}
                    onClick={() => handleRowClick(c)}
                    hover
                    selected={isActive}
                    sx={{
                      cursor: 'pointer',
                      ...(isActive && {
                        backgroundColor: 'rgba(74, 118, 196, 0.18) !important',
                        '& .MuiTableCell-root': { fontWeight: 600 },
                      }),
                    }}
                  >
                    <TableCell sx={{ py: 0.25 }}>
                      <Chip
                        label={c.severity}
                        size="small"
                        sx={{
                          height: 16,
                          fontSize: '0.55rem',
                          bgcolor: `${sevColor}22`,
                          color: sevColor,
                          textTransform: 'uppercase',
                          letterSpacing: 0.5,
                          fontWeight: 700,
                        }}
                      />
                    </TableCell>
                    <TableCell sx={{ py: 0.25, fontSize: '0.75rem', fontFamily: 'ui-monospace, monospace', color: sevColor, fontWeight: 600 }}>
                      {c.overlap.toFixed(2)}
                    </TableCell>
                    <TableCell sx={{ py: 0.25, fontSize: '0.7rem', fontFamily: 'ui-monospace, monospace' }}>
                      {c.distance.toFixed(2)}
                    </TableCell>
                    <TableCell sx={{ py: 0.25, fontSize: '0.7rem' }}>
                      <Box component="span" sx={{ fontWeight: 600 }}>{c.chainA}</Box>
                      {' '}{c.resNameA} {c.resIdA}{' · '}
                      <Box component="span" sx={{ fontFamily: 'ui-monospace, monospace' }}>{c.atomA}</Box>
                    </TableCell>
                    <TableCell sx={{ py: 0.25, fontSize: '0.7rem' }}>
                      <Box component="span" sx={{ fontWeight: 600 }}>{c.chainB}</Box>
                      {' '}{c.resNameB} {c.resIdB}{' · '}
                      <Box component="span" sx={{ fontFamily: 'ui-monospace, monospace' }}>{c.atomB}</Box>
                    </TableCell>
                  </TableRow>
                )
              })}

              {groupByResidue && groups.map(g => {
                const isOpen = expanded.has(g.key)
                const activeInGroup = g.clashes.some(c => c.id === activeId)
                const sevColor = g.worstSeverity === 'severe' ? '#c62828' : '#e68a00'
                const totalCount = g.clashes.length
                const sevLabel = totalCount > 1
                  ? `${g.worstSeverity} × ${totalCount}`
                  : g.worstSeverity
                return (
                  <Fragment key={g.key}>
                    <TableRow
                      hover
                      selected={activeInGroup}
                      onClick={() => handleGroupClick(g)}
                      sx={{
                        cursor: 'pointer',
                        ...(activeInGroup && {
                          backgroundColor: 'rgba(74, 118, 196, 0.18) !important',
                          '& .MuiTableCell-root': { fontWeight: 600 },
                        }),
                      }}
                    >
                      <TableCell sx={{ py: 0.25, p: 0, width: 28 }}>
                        <IconButton
                          aria-label={isOpen ? 'Collapse residue pair' : 'Expand residue pair'}
                          aria-expanded={isOpen}
                          size="small"
                          onClick={(e) => { e.stopPropagation(); toggleExpanded(g.key) }}
                          sx={compactIconButtonSx}
                        >
                          {isOpen
                            ? <ExpandMoreIcon sx={{ fontSize: 16 }} />
                            : <ChevronRightIcon sx={{ fontSize: 16 }} />}
                        </IconButton>
                      </TableCell>
                      <TableCell sx={{ py: 0.25 }}>
                        <Chip
                          label={sevLabel}
                          size="small"
                          sx={{
                            height: 16,
                            fontSize: '0.55rem',
                            bgcolor: `${sevColor}22`,
                            color: sevColor,
                            textTransform: 'uppercase',
                            letterSpacing: 0.5,
                            fontWeight: 700,
                          }}
                        />
                      </TableCell>
                      <TableCell sx={{ py: 0.25, fontSize: '0.75rem', fontFamily: 'ui-monospace, monospace', color: sevColor, fontWeight: 600 }}>
                        {g.worstOverlap.toFixed(2)}
                      </TableCell>
                      <TableCell sx={{ py: 0.25, fontSize: '0.7rem', color: 'text.secondary' }}>—</TableCell>
                      <TableCell sx={{ py: 0.25, fontSize: '0.7rem' }}>
                        <Box component="span" sx={{ fontWeight: 600 }}>{g.chainA}</Box>
                        {' '}{g.resNameA} {g.resIdA}
                        <Box sx={{ fontSize: '0.6rem', color: 'text.secondary', mt: 0.1 }}>
                          {totalCount} atom{totalCount > 1 ? 's' : ''}
                        </Box>
                      </TableCell>
                      <TableCell sx={{ py: 0.25, fontSize: '0.7rem' }}>
                        <Box component="span" sx={{ fontWeight: 600 }}>{g.chainB}</Box>
                        {' '}{g.resNameB} {g.resIdB}
                      </TableCell>
                    </TableRow>

                    {isOpen && g.clashes.map(c => {
                      const isActive = activeId === c.id
                      const cSevColor = c.severity === 'severe' ? '#c62828' : '#e68a00'
                      // Render endpoints in the same A/B orientation as the group header.
                      const flip = c.chainA !== g.chainA || c.resIdA !== g.resIdA
                      const lhs = flip
                        ? { chain: c.chainB, resName: c.resNameB, resId: c.resIdB, atom: c.atomB }
                        : { chain: c.chainA, resName: c.resNameA, resId: c.resIdA, atom: c.atomA }
                      const rhs = flip
                        ? { chain: c.chainA, resName: c.resNameA, resId: c.resIdA, atom: c.atomA }
                        : { chain: c.chainB, resName: c.resNameB, resId: c.resIdB, atom: c.atomB }
                      return (
                        <TableRow
                          key={c.id}
                          hover
                          selected={isActive}
                          onClick={() => handleRowClick(c)}
                          sx={{
                            cursor: 'pointer',
                            backgroundColor: 'rgba(0, 0, 0, 0.015)',
                            ...(isActive && {
                              backgroundColor: 'rgba(74, 118, 196, 0.22) !important',
                              '& .MuiTableCell-root': { fontWeight: 600 },
                            }),
                          }}
                        >
                          <TableCell sx={{ py: 0.25, p: 0, width: 28 }} />
                          <TableCell sx={{ py: 0.2, pl: 2.5 }}>
                            <Chip
                              label={c.severity}
                              size="small"
                              sx={{
                                height: 14,
                                fontSize: '0.5rem',
                                bgcolor: `${cSevColor}22`,
                                color: cSevColor,
                                textTransform: 'uppercase',
                                letterSpacing: 0.5,
                                fontWeight: 700,
                              }}
                            />
                          </TableCell>
                          <TableCell sx={{ py: 0.2, fontSize: '0.7rem', fontFamily: 'ui-monospace, monospace', color: cSevColor, fontWeight: 600 }}>
                            {c.overlap.toFixed(2)}
                          </TableCell>
                          <TableCell sx={{ py: 0.2, fontSize: '0.7rem', fontFamily: 'ui-monospace, monospace' }}>
                            {c.distance.toFixed(2)}
                          </TableCell>
                          <TableCell sx={{ py: 0.2, fontSize: '0.7rem' }}>
                            <Box component="span" sx={{ color: 'text.secondary' }}>{lhs.chain} {lhs.resName} {lhs.resId} · </Box>
                            <Box component="span" sx={{ fontFamily: 'ui-monospace, monospace', fontWeight: 600 }}>{lhs.atom}</Box>
                          </TableCell>
                          <TableCell sx={{ py: 0.2, fontSize: '0.7rem' }}>
                            <Box component="span" sx={{ color: 'text.secondary' }}>{rhs.chain} {rhs.resName} {rhs.resId} · </Box>
                            <Box component="span" sx={{ fontFamily: 'ui-monospace, monospace', fontWeight: 600 }}>{rhs.atom}</Box>
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </Fragment>
                )
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Box>
  )
}
