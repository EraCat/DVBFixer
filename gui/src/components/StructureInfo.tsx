import { useEffect, useMemo, useRef, useState } from 'react'
import Box from '@mui/material/Box'
import { formActionRowSx } from '../ui/layout'
import Typography from '@mui/material/Typography'
import TextField from '@mui/material/TextField'
import Paper from '@mui/material/Paper'
import Chip from '@mui/material/Chip'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import AddIcon from '@mui/icons-material/Add'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutlined'
import MenuItem from '@mui/material/MenuItem'
import { useStructureStore, type StructureMeta } from '../stores/structureStore'
import { computeEquivalentChains, filterSequenceableChains, validateGrouping } from '../lib/chain-grouping'
import { useWorkspaceStore } from '../stores/workspaceStore'

const META_FIELDS: Array<keyof StructureMeta> = ['name', 'organism', 'method', 'resolution', 'description', 'iggSubtype', 'allotype', 'equivalentChains']

const IGG_SUBTYPES = ['', 'IgG1', 'IgG2', 'IgG3', 'IgG4', 'IgA', 'IgM', 'IgE', 'IgD']

// Deep-equality check for the equivalentChains field (`string[][]`). Used by
// the meta-changed detector so a deserialized array doesn't fire spurious
// saves on every render.
function chainGroupsEqual(a: string[][] | undefined, b: string[][] | undefined): boolean {
  if (a === b) return true
  if (!a || !b) return false
  if (a.length !== b.length) return false
  for (let i = 0; i < a.length; i++) {
    const ga = a[i], gb = b[i]
    if (ga.length !== gb.length) return false
    for (let j = 0; j < ga.length; j++) if (ga[j] !== gb[j]) return false
  }
  return true
}

function metaFieldChanged(key: keyof StructureMeta, a: StructureMeta, b: StructureMeta): boolean {
  if (key === 'equivalentChains') return !chainGroupsEqual(a.equivalentChains, b.equivalentChains)
  return a[key] !== b[key]
}

export function StructureInfo() {
  const meta = useStructureStore((s) => s.meta)
  const setMeta = useStructureStore((s) => s.setMeta)
  const fileName = useStructureStore((s) => s.fileName)
  const chains = useStructureStore((s) => s.chains)
  const elements = useStructureStore((s) => s.elements)
  const workspace = useWorkspaceStore((s) => s.active)
  const updateArtifactMetadata = useWorkspaceStore((s) => s.updateArtifactMetadata)

  // Persist meta edits on the active workspace artifact.
  // Debounced so we don't write on every keystroke. Resets when the loaded
  // file changes so the new structure's meta isn't immediately overwritten
  // by the just-loaded values.
  const lastSavedFileRef = useRef<string | null>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined)
  const initialMetaRef = useRef<StructureMeta | null>(null)

  useEffect(() => {
    // When the loaded file changes, snapshot the meta-on-load. Subsequent
    // saves only fire if any field differs from the snapshot.
    initialMetaRef.current = { ...meta }
    lastSavedFileRef.current = fileName
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileName])

  useEffect(() => {
    if (!fileName) return
    const artifact = workspace?.artifacts.find(item => item.file === fileName)
    if (!artifact) return
    if (lastSavedFileRef.current !== fileName) return // file just switched
    if (!initialMetaRef.current) return
    // Compare against the initial snapshot. equivalentChains needs deep
    // compare, the others are strings.
    const changed = META_FIELDS.some(k => metaFieldChanged(k, meta, initialMetaRef.current!))
    if (!changed) return
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      try {
        await updateArtifactMetadata(artifact.id, {
          name: meta.name,
          organism: meta.organism || null,
          method: meta.method || null,
          resolution: meta.resolution || null,
          description: meta.description || null,
          iggSubtype: meta.iggSubtype || null,
          allotype: meta.allotype || null,
          equivalentChains: meta.equivalentChains ?? null,
        })
        initialMetaRef.current = { ...meta }
      } catch (err) {
        console.warn('[info] failed to persist meta:', err)
      }
    }, 500)
    return () => clearTimeout(debounceRef.current)
  }, [meta, fileName, updateArtifactMetadata, workspace])

  if (!fileName) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%' }}>
        <Typography variant="caption" sx={{ color: 'text.secondary' }}>Load a structure to see its info</Typography>
      </Box>
    )
  }

  // Summary counts: only count "real" polypeptide/nucleotide chains
  // (drop water/ion-only chains, all-X glycans, etc.) — same filter used
  // by the Sequence and Equivalent-chains sections so the numbers agree.
  const proteinChains = filterSequenceableChains(chains)
  const totalResidues = proteinChains.reduce((s, c) => s + c.residues.length, 0)
  const totalAtoms = elements.reduce((s, e) => s + e.atomCount, 0)

  return (
    <Box sx={{ height: '100%', overflow: 'auto', p: 1.5 }}>
      <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>
        Summary
      </Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 1, mt: 0.5, mb: 2 }}>
        <StatCard label="Chains" value={proteinChains.length} />
        <StatCard label="Residues" value={totalResidues} />
        <StatCard label="Atoms" value={totalAtoms} />
        <StatCard label="Elements" value={elements.length} />
      </Box>

      <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>
        File
      </Typography>
      <Paper
        variant="outlined"
        sx={{
          px: 1.5, py: 1, mt: 0.5, mb: 2,
          fontFamily: 'monospace', fontSize: '0.75rem',
          // Allow long paths (e.g. dvb_<cmd>_<ts>/<input>_<cmd>.pdb) to wrap
          // instead of overflowing horizontally.
          wordBreak: 'break-all', whiteSpace: 'normal',
        }}
      >
        {fileName}
      </Paper>

      <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>
        Metadata
      </Typography>
      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, mt: 0.5, mb: 2 }}>
        <TextField label="Name" value={meta.name} onChange={(e) => setMeta({ name: e.target.value })} fullWidth />
        <Box sx={formActionRowSx}>
          <TextField
            select
            label="IgG Subtype"
            value={meta.iggSubtype ?? ''}
            onChange={(e) => setMeta({ iggSubtype: e.target.value })}
            sx={{ flex: '1 1 140px', minWidth: 0 }}
          >
            {IGG_SUBTYPES.map(opt => (
              <MenuItem key={opt || '__empty__'} value={opt}>{opt || <em>— none —</em>}</MenuItem>
            ))}
          </TextField>
          <TextField
            label="Allotype"
            value={meta.allotype ?? ''}
            onChange={(e) => setMeta({ allotype: e.target.value })}
            placeholder="e.g. G1m17,1 or nG1m1"
            sx={{ flex: '1 1 140px', minWidth: 0 }}
          />
        </Box>
      </Box>

      <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>
        Notes
      </Typography>
      <TextField
        value={meta.description}
        onChange={(e) => setMeta({ description: e.target.value })}
        placeholder="Add notes about this structure..."
        multiline
        minRows={3}
        fullWidth
        sx={{ mt: 0.5, mb: 2 }}
      />

      <EquivalentChainsSection />
    </Box>
  )
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <Paper variant="outlined" sx={{ px: 1.5, py: 1 }}>
      <Typography variant="h6" sx={{ fontFamily: 'monospace', fontWeight: 700, fontSize: '1rem' }}>
        {value.toLocaleString()}
      </Typography>
      <Typography variant="caption" sx={{ color: 'text.secondary' }}>{label}</Typography>
    </Paper>
  )
}

/**
 * Display + edit the equivalent-chain groups for the loaded structure.
 * Auto-detected via pairwise sequence identity (≥ 95 % after trimming
 * terminal gaps) by default; user can override and the override is
 * persisted in `index.json` via the same debounced-PUT pipeline as the
 * rest of the meta fields.
 */
function EquivalentChainsSection() {
  const chains = useStructureStore((s) => s.chains)
  const override = useStructureStore((s) => s.meta.equivalentChains)
  const setMeta = useStructureStore((s) => s.setMeta)

  // Polypeptide / nucleotide chain ids available for grouping (matches the
  // filter used everywhere else — no glycans, no ion-only chains).
  const availableIds = useMemo(
    () => filterSequenceableChains(chains).map(c => c.id),
    [chains]
  )

  // Auto-computed groups. Cheap for typical N ≤ 20; useMemo keeps it
  // stable across unrelated re-renders.
  const autoGroups = useMemo(() => computeEquivalentChains(chains), [chains])

  // What we display: the override if set, otherwise the auto groups.
  // Both produce the same `ChainGroup`-ish shape; for an override we
  // recompute the identity from auto-groups when possible (for display only).
  const displayGroups = useMemo(() => {
    if (!override) return autoGroups
    // Map auto-group identities by sorted-id key so we can decorate the
    // user's groups with the identity number where it makes sense.
    const autoByKey = new Map(
      autoGroups.map(g => [g.chainIds.slice().sort().join(','), g])
    )
    return override.map(ids => {
      const sorted = ids.slice().sort((a, b) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' }))
      const match = autoByKey.get(sorted.join(','))
      return {
        chainIds: sorted,
        identity: match?.identity ?? null,
        alignmentLength: match?.alignmentLength ?? null,
      }
    })
  }, [override, autoGroups])

  const [editing, setEditing] = useState(false)
  const [drafts, setDrafts] = useState<string[]>([])
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const startEditing = () => {
    const sourceGroups: string[][] = override
      ? override
      : autoGroups.filter(g => g.chainIds.length > 1).map(g => g.chainIds)
    setDrafts(sourceGroups.map(g => g.join(', ')))
    setErrorMsg(null)
    setEditing(true)
  }

  const cancelEditing = () => {
    setDrafts([])
    setErrorMsg(null)
    setEditing(false)
  }

  const saveDrafts = () => {
    const parsed: string[][] = drafts
      .map(line => line.split(',').map(t => t.trim()).filter(Boolean))
      .filter(g => g.length > 0)
    const result = validateGrouping(parsed, availableIds)
    if (result.unknown.length > 0) {
      setErrorMsg(`Unknown chain id${result.unknown.length > 1 ? 's' : ''}: ${result.unknown.join(', ')}`)
      return
    }
    if (result.duplicates.length > 0) {
      setErrorMsg(`Chain${result.duplicates.length > 1 ? 's' : ''} listed in more than one group: ${result.duplicates.join(', ')}`)
      return
    }
    setMeta({ equivalentChains: result.canonical })
    setEditing(false)
    setErrorMsg(null)
  }

  const resetToAuto = () => {
    setMeta({ equivalentChains: undefined })
    setEditing(false)
    setErrorMsg(null)
  }

  if (availableIds.length === 0) return null

  // Singletons (chains not in any multi-member group) — rolled into one
  // de-emphasised row at the bottom.
  const placed = new Set(displayGroups.filter(g => g.chainIds.length > 1).flatMap(g => g.chainIds))
  const singletons = availableIds.filter(id => !placed.has(id))
  const multiMember = displayGroups.filter(g => g.chainIds.length > 1)

  return (
    <Box sx={{ mb: 2 }}>
      <Box sx={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 1, mb: 1 }}>
        <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>
          Equivalent chains
        </Typography>
        {override !== undefined && (
          <Chip label="manual" size="small" color="warning" />
        )}
        <Box sx={{ flex: 1 }} />
        {!editing && (
          <>
            <Button size="small" variant="outlined" onClick={startEditing}>
              Edit groups
            </Button>
            {override !== undefined && (
              <Tooltip title="Discard manual grouping and use sequence-identity auto-detection">
                <Button size="small" onClick={resetToAuto}>
                  Reset
                </Button>
              </Tooltip>
            )}
          </>
        )}
        {editing && (
          <>
            <Button size="small" onClick={cancelEditing}>
              Cancel
            </Button>
            <Button size="small" variant="contained" onClick={saveDrafts}>
              Save
            </Button>
          </>
        )}
      </Box>

      {!editing && multiMember.length === 0 && (
        <Typography variant="caption" sx={{ color: 'text.secondary', fontStyle: 'italic' }}>
          No equivalent chains detected — every chain looks unique.
        </Typography>
      )}

      {!editing && multiMember.map((g, idx) => (
        <Paper key={idx} variant="outlined" sx={{ px: 1, py: 0.75, mb: 0.5, display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
          {g.chainIds.map(id => {
            const missing = !availableIds.includes(id)
            return (
              <Chip
                key={id}
                label={missing ? `${id} (missing)` : id}
                size="small"
                color={missing ? 'error' : 'primary'}
                variant={missing ? 'outlined' : 'filled'}
                sx={{ fontWeight: 600 }}
              />
            )
          })}
          <Box sx={{ flex: 1 }} />
          {g.identity !== null && g.alignmentLength !== null && (
            <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem' }}>
              {(g.identity * 100).toFixed(1)} % over {g.alignmentLength} aa
            </Typography>
          )}
        </Paper>
      ))}

      {!editing && singletons.length > 0 && (
        <Box sx={{ mt: 0.5, display: 'flex', alignItems: 'center', gap: 0.5, flexWrap: 'wrap' }}>
          <Typography variant="caption" sx={{ color: 'text.disabled', fontSize: '0.65rem' }}>
            Unique:
          </Typography>
          {singletons.map(id => (
            <Chip key={id} label={id} size="small" variant="outlined" />
          ))}
        </Box>
      )}

      {editing && (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 0.5 }}>
          <Typography variant="caption" sx={{ color: 'text.secondary', fontSize: '0.65rem' }}>
            One group per row — comma-separate chain ids. Chains left out become singletons.
          </Typography>
          {drafts.map((line, idx) => (
            <Box key={idx} sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
              <TextField
                size="small"
                value={line}
                onChange={(e) => setDrafts(d => d.map((v, i) => i === idx ? e.target.value : v))}
                placeholder="e.g. H, I"
                fullWidth
              />
              <IconButton aria-label={`Remove chain group ${idx + 1}`} size="small" onClick={() => setDrafts(d => d.filter((_, i) => i !== idx))}>
                <DeleteOutlineIcon sx={{ fontSize: 16 }} />
              </IconButton>
            </Box>
          ))}
          <Button
            size="small"
            startIcon={<AddIcon sx={{ fontSize: 14 }} />}
            onClick={() => setDrafts(d => [...d, ''])}
            sx={{ alignSelf: 'flex-start' }}
          >
            Add group
          </Button>
          {errorMsg && (
            <Typography variant="caption" sx={{ color: 'error.main', fontSize: '0.65rem' }}>
              {errorMsg}
            </Typography>
          )}
        </Box>
      )}
    </Box>
  )
}
