import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent as ReactMouseEvent, type ReactNode } from 'react'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import FormControl from '@mui/material/FormControl'
import IconButton from '@mui/material/IconButton'
import InputLabel from '@mui/material/InputLabel'
import MenuItem from '@mui/material/MenuItem'
import Select from '@mui/material/Select'
import Tab from '@mui/material/Tab'
import Tabs from '@mui/material/Tabs'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/DeleteOutlined'
import RedoIcon from '@mui/icons-material/Redo'
import UndoIcon from '@mui/icons-material/Undo'
import AccountTreeIcon from '@mui/icons-material/AccountTree'
import LinkIcon from '@mui/icons-material/Link'
import LinkOffIcon from '@mui/icons-material/LinkOff'
import { useStructureStore } from '../stores/structureStore'
import { useWorkspaceStore, workspaceFileUrl } from '../stores/workspaceStore'
import { useSelectionStore } from '../stores/selectionStore'
import { alignmentColumnsForResidues, alignmentColumnsToSpans, comparisonToReference, consensusFor, updateColumnSelection } from '../lib/homology-alignment'
import { bestMatchingChainId, chainIdentityLabel, targetSequences } from '../lib/homology-templates'
import { residueClass, RESIDUE_CLASS_COLORS } from '../lib/residue-codes'
import { apiFetch } from '../lib/api-client'
import { structureMetaFromArtifact } from '../lib/workspace-metadata'

interface TemplateSelection {
  id: string
  file: string
  chain: string
  targetChain: string
  label?: string
  fittedFile?: string
}
interface AlignmentSpan { start: number; end: number }
interface AlignmentRow {
  id: string
  kind: 'target' | 'template'
  sequence: string
  templateId?: string
}
interface AlignmentGroup {
  chainId: string
  rows: AlignmentRow[]
  masks: Record<string, AlignmentSpan[]>
  maskModes?: Record<string, 'all' | 'ranges' | 'none'>
}
interface HomologyProject {
  version: 1
  id: string
  name: string
  targetFasta: string
  templates: TemplateSelection[]
  engine: 'mafft' | 'muscle' | 'clustalo'
  alignmentGroups: AlignmentGroup[]
  structuralAlignment?: string | Record<string, string>
  modelOptions: Record<string, string | number | boolean>
  createdAt: string
  updatedAt: string
}
interface ProjectSummary { id: string; name: string; updatedAt: string }
interface EngineStatus { available: boolean; path: string | null }
interface ParsedChain { id: string; length: number; sequence: string }
interface TransientAlignmentSelection { anchor: number; columns: number[] }

const homologyToolbarSx = {
  display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap',
  px: 1, py: 0.5, minHeight: 40,
  '& .MuiButton-root': { width: 160, minWidth: 160, height: 32, flexShrink: 0 },
  '& .MuiFormControl-root': { width: 160, minWidth: 160, flexShrink: 0 },
  '& .MuiInputBase-root': { height: 32 },
  '& .MuiInputLabel-root:not(.MuiInputLabel-shrink)': {
    transform: 'translate(14px, 5px) scale(1)',
  },
  '& .MuiInputLabel-root.MuiInputLabel-shrink': {
    transform: 'translate(14px, -8px) scale(0.75)',
  },
  '& .MuiSelect-select, & .MuiInputBase-input': {
    display: 'flex', alignItems: 'center', py: '5px', boxSizing: 'border-box',
  },
  '& .MuiIconButton-root': { width: 32, height: 32, flexShrink: 0 },
} as const

const projectToolbarSx = {
  px: 1, py: 0.75, display: 'flex', gap: 1, alignItems: 'center',
  minHeight: 48, borderBottom: 1, borderColor: 'divider',
  '& .MuiInputBase-root': { height: 32 },
  '& .MuiIconButton-root': { width: 32, height: 32 },
} as const

const toolbarControlSx = { width: 160, minWidth: 160 } as const
const targetSourceControlSx = { width: 320, minWidth: 320 } as const
const toolbarTooltipWrapperSx = {
  display: 'inline-flex', width: 160, height: 32, flexShrink: 0,
} as const
const primaryActionSx = { width: 160, minWidth: 160, height: 32, alignSelf: 'center' } as const


function targetChainIds(fasta: string): string[] {
  return fasta.split(/\r?\n/)
    .filter(line => line.trim().startsWith('>'))
    .map(line => line.trim().slice(1).split(/\s+/)[0])
    .filter(Boolean)
}

function cloneGroups(groups: AlignmentGroup[]): AlignmentGroup[] {
  return JSON.parse(JSON.stringify(groups)) as AlignmentGroup[]
}

const ALIGNMENT_LABEL_WIDTH = 270

function AlignmentCells({ label, sequence, annotation = false }: { label: ReactNode; sequence: string; annotation?: boolean }) {
  return <Box sx={{ display: 'flex', alignItems: 'center', minWidth: 'max-content', mb: annotation ? 0.15 : 0.5 }}>
    <Box sx={{ position: 'sticky', left: 0, zIndex: 3, bgcolor: 'background.paper', width: ALIGNMENT_LABEL_WIDTH, flexShrink: 0, px: 1 }}>
      <Typography variant="caption" color="text.secondary">{label}</Typography>
    </Box>
    {Array.from(sequence).map((character, column) => <Box key={column} sx={{ width: 16, height: annotation ? 13 : 18, display: 'flex', alignItems: 'center', justifyContent: 'center', lineHeight: 1, textAlign: 'center', fontSize: annotation ? 9 : 12, fontWeight: character === '*' ? 800 : 400, color: character === '*' ? 'primary.main' : 'text.secondary' }}>{character}</Box>)}
  </Box>
}

export function HomologyPanel() {
  const [project, setProject] = useState<HomologyProject | null>(null)
  const [projects, setProjects] = useState<ProjectSummary[]>([])
  const [engines, setEngines] = useState<Record<string, EngineStatus>>({})
  const [chainsByFile, setChainsByFile] = useState<Record<string, ParsedChain[]>>({})
  const [targetSource, setTargetSource] = useState('')
  const [parsePreview, setParsePreview] = useState<Array<{ id: string; sequence: string; length: number; selected: boolean }>>([])
  const [activeTargetChain, setActiveTargetChain] = useState('')
  const [selectionSyncEnabled, setSelectionSyncEnabled] = useState(true)
  const [tab, setTab] = useState(0)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [saved, setSaved] = useState(true)
  const [selection, setSelection] = useState<Record<string, TransientAlignmentSelection>>({})
  const [undo, setUndo] = useState<AlignmentGroup[][]>([])
  const [redo, setRedo] = useState<AlignmentGroup[][]>([])
  const alignmentImportRef = useRef<HTMLInputElement>(null)
  const alignmentDragRef = useRef<{ groupIndex: number; rowId: string; anchor: number; moved: boolean } | null>(null)
  const projectRequestRef = useRef(0)
  const primaryFile = useStructureStore(state => state.fileName)
  const primaryChain = useStructureStore(state => state.activeChainId)

  useEffect(() => {
    const stopDrag = () => { alignmentDragRef.current = null }
    window.addEventListener('mouseup', stopDrag)
    return () => window.removeEventListener('mouseup', stopDrag)
  }, [])
  const plugin = useStructureStore(state => state.plugin)
  const setFileName = useStructureStore(state => state.setFileName)
  const selected3dResidues = useSelectionStore(state => state.selectedResidues)
  const activeWorkspace = useWorkspaceStore(state => state.active)
  const activeWorkspaceId = activeWorkspace?.id || ''
  const reloadWorkspace = useWorkspaceStore(state => state.reload)
  const updateWorkspaceToolState = useWorkspaceStore(state => state.updateToolState)
  const artifacts = (activeWorkspace?.artifacts || []).filter(entry => !entry.hidden).map(entry => ({ file: entry.file, name: entry.name, kind: entry.kind }))

  const refreshProjects = useCallback(async () => {
    if (!activeWorkspaceId) { setProjects([]); return }
    const workspaceId = activeWorkspaceId
    const response = await apiFetch(`/api/homology/projects?workspaceId=${encodeURIComponent(activeWorkspaceId)}`, { cache: 'no-store' })
    if (!response.ok) throw new Error(`Projects: HTTP ${response.status}`)
    const list = await response.json() as ProjectSummary[]
    if (useWorkspaceStore.getState().active?.id !== workspaceId) return
    setProjects(list)
    return list
  }, [activeWorkspaceId])

  const loadProject = useCallback(async (id: string) => {
    const request = ++projectRequestRef.current
    const workspaceId = activeWorkspaceId
    setBusy('Loading project')
    try {
      if (!workspaceId) return
      const response = await apiFetch(`/api/homology/projects/${encodeURIComponent(id)}?workspaceId=${encodeURIComponent(workspaceId)}`, { cache: 'no-store' })
      const body = await response.json() as HomologyProject & { error?: string }
      if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`)
      if (request !== projectRequestRef.current || useWorkspaceStore.getState().active?.id !== workspaceId) return
      setProject(body)
      setSelection({})
      setUndo([])
      setRedo([])
      setSaved(true)
    } finally {
      if (request === projectRequestRef.current) setBusy('')
    }
  }, [activeWorkspaceId])

  const createProject = useCallback(async () => {
    const request = ++projectRequestRef.current
    const workspaceId = activeWorkspaceId
    setBusy('Creating project')
    setError('')
    try {
      if (!workspaceId) return
      const response = await apiFetch('/api/homology/projects', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspaceId }) })
      const body = await response.json() as HomologyProject & { error?: string }
      if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`)
      if (request !== projectRequestRef.current || useWorkspaceStore.getState().active?.id !== workspaceId) return
      setProject(body)
      setSelection({})
      await refreshProjects()
      setSaved(true)
    } catch (reason: any) {
      setError(reason.message || String(reason))
    } finally {
      if (request === projectRequestRef.current) setBusy('')
    }
  }, [activeWorkspaceId, refreshProjects])

  useEffect(() => {
    const request = ++projectRequestRef.current
    setProject(null)
    setSelection({})
    setProjects([])
    setChainsByFile({})
    if (!activeWorkspaceId) return
    refreshProjects()
      .then(async (list = []) => {
        if (request !== projectRequestRef.current) return
        const preferred = (useWorkspaceStore.getState().active?.toolState?.homology as any)?.projectId
        const selected = list.find(item => item.id === preferred) || list[0]
        if (selected) await loadProject(selected.id)
        else await createProject()
      })
      .catch(reason => { if (request === projectRequestRef.current) setError(reason.message || String(reason)) })
    return () => { projectRequestRef.current = request + 1 }
  }, [activeWorkspaceId, createProject, loadProject, refreshProjects])

  useEffect(() => {
    const state = activeWorkspace?.toolState?.homology as any
    setTab(typeof state?.tab === 'number' ? state.tab : 0)
    setActiveTargetChain(state?.activeTargetChain || '')
    setSelectionSyncEnabled(state?.selectionSyncEnabled !== false)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWorkspaceId])

  useEffect(() => {
    if (!activeWorkspace || !project) return
    updateWorkspaceToolState('homology', { projectId: project.id, tab, activeTargetChain, selectionSyncEnabled })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, tab, activeTargetChain, selectionSyncEnabled])

  useEffect(() => {
    apiFetch('/api/homology/engines', { cache: 'no-store' })
      .then(response => response.ok ? response.json() : {})
      .then((status: Record<string, EngineStatus>) => setEngines(status))
      .catch(() => setEngines({}))
  }, [])

  useEffect(() => {
    if (!project || saved) return
    const timer = window.setTimeout(async () => {
      try {
        const response = await apiFetch(`/api/homology/projects/${encodeURIComponent(project.id)}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...project, workspaceId: activeWorkspaceId }),
        })
        if (!response.ok) throw new Error(`Autosave: HTTP ${response.status}`)
        setSaved(true)
        refreshProjects().catch(() => {})
      } catch (reason: any) {
        setError(reason.message || String(reason))
      }
    }, 700)
    return () => window.clearTimeout(timer)
  }, [activeWorkspaceId, project, refreshProjects, saved])

  const update = useCallback((patch: Partial<HomologyProject>) => {
    setProject(current => current ? { ...current, ...patch } : current)
    setSaved(false)
  }, [])

  const targetChains = useMemo(() => targetChainIds(project?.targetFasta || ''), [project?.targetFasta])
  const targetSequenceByChain = useMemo(
    () => targetSequences(project?.targetFasta || ''),
    [project?.targetFasta],
  )
  const visibleTemplates = useMemo(
    () => (project?.templates || []).filter(template => template.targetChain === activeTargetChain),
    [activeTargetChain, project?.templates],
  )
  const targetSourceSupported = /\.(pdb|cif|mmcif|fasta|fa|faa|pir|aln|txt)$/i.test(targetSource)

  useEffect(() => {
    if (!activeTargetChain || !targetChains.includes(activeTargetChain)) setActiveTargetChain(targetChains[0] || '')
  }, [activeTargetChain, targetChains])

  const fetchChains = useCallback(async (file: string): Promise<ParsedChain[]> => {
    const workspaceId = activeWorkspaceId
    if (!workspaceId || !file) return []
    if (chainsByFile[file]) return chainsByFile[file]
    const response = await apiFetch('/api/homology/chains', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ workspaceId, file }) })
    const body = await response.json() as ParsedChain[] & { error?: string }
    if (!response.ok) throw new Error((body as any).error || `HTTP ${response.status}`)
    if (useWorkspaceStore.getState().active?.id !== workspaceId) return []
    setChainsByFile(current => ({ ...current, [file]: body }))
    return body
  }, [activeWorkspaceId, chainsByFile])

  useEffect(() => {
    for (const template of project?.templates || []) fetchChains(template.file).catch(() => {})
  }, [fetchChains, project?.templates])

  const addTemplate = async () => {
    if (!project) return
    const activeIsWorkspaceStructure = !!primaryFile && artifacts.some(
      item => item.file === primaryFile && item.kind === 'structure',
    )
    const file = activeIsWorkspaceStructure ? primaryFile : ''
    let chain = activeIsWorkspaceStructure ? primaryChain || '' : ''
    if (file) {
      try {
        const chains = await fetchChains(file)
        chain = bestMatchingChainId(
          chains,
          targetSequenceByChain[activeTargetChain] || '',
          chain,
        )
      } catch (reason: any) {
        setError(reason.message || String(reason))
        chain = ''
      }
    }
    const template: TemplateSelection = {
      id: crypto.randomUUID(), file, chain, targetChain: activeTargetChain || targetChains[0] || '',
    }
    update({ templates: [...project.templates, template] })
  }

  const updateTemplate = (id: string, patch: Partial<TemplateSelection>) => {
    if (!project) return
    update({ templates: project.templates.map(template => template.id === id ? { ...template, ...patch } : template) })
  }

  const parseTargetSource = async () => {
    if (!activeWorkspace || !project || !targetSource) return
    setBusy('Parsing sequence')
    setError('')
    try {
      const response = await apiFetch('/api/homology/parse-sequence', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ workspaceId: activeWorkspace.id, file: targetSource }),
      })
      const body = await response.json() as { records?: Array<{ id: string; sequence: string; length: number }>; error?: string }
      if (!response.ok || !body.records?.length) throw new Error(body.error || 'No protein sequences detected')
      const records = body.records.map(record => ({ ...record, selected: true }))
      setParsePreview(records)
      update({ targetFasta: records.map(record => `>${record.id}\n${record.sequence}\n`).join(''), alignmentGroups: [] })
      setMessage(`Parsed ${records.length} target sequence(s) from ${targetSource}`)
    } catch (reason: any) { setError(reason.message || String(reason)) } finally { setBusy('') }
  }

  const applyParsedTarget = () => {
    const records = parsePreview.filter(record => record.selected)
    if (!records.length) { setError('Select at least one parsed sequence'); return }
    if (records.some(record => !record.id.trim()) || new Set(records.map(record => record.id.trim())).size !== records.length) {
      setError('Parsed target IDs must be non-empty and unique'); return
    }
    update({ targetFasta: records.map(record => `>${record.id.trim()}\n${record.sequence}\n`).join(''), alignmentGroups: [] })
    setParsePreview([])
    setMessage(`Loaded ${records.length} target sequence(s) from ${targetSource}`)
  }

  const changeTemplateFile = async (template: TemplateSelection, file: string) => {
    try {
      const chains = await fetchChains(file)
      const chain = bestMatchingChainId(
        chains,
        targetSequenceByChain[template.targetChain] || '',
      )
      updateTemplate(template.id, { file, chain })
      if (project) update({ alignmentGroups: [] })
    } catch (reason: any) { setError(reason.message || String(reason)) }
  }

  const loadTemplateInPrimary = async (template: TemplateSelection) => {
    if (!activeWorkspace || !plugin || primaryFile === template.file) return
    const response = await apiFetch(workspaceFileUrl(activeWorkspace.id, template.file))
    if (!response.ok) throw new Error(`Unable to load template: HTTP ${response.status}`)
    await plugin.clear()
    const data = await plugin.builders.data.rawData({ data: await response.text(), label: template.file })
    const trajectory = await plugin.builders.structure.parseTrajectory(data, /\.(cif|mmcif)$/i.test(template.file) ? 'mmcif' : 'pdb')
    await plugin.builders.structure.hierarchy.applyPreset(trajectory, 'default', {
      structure: { name: 'model', params: {} },
    })
    const artifact = activeWorkspace.artifacts.find(item => item.file === template.file)
    if (artifact) useStructureStore.getState().setMeta(structureMetaFromArtifact(artifact))
    setFileName(template.file)
    useWorkspaceStore.getState().update({ primaryFile: template.file })
  }

  const selectTemplateColumns = async (row: AlignmentRow, column: number,
    event: Pick<ReactMouseEvent, 'shiftKey' | 'ctrlKey' | 'metaKey' | 'altKey'>,
    explicitAnchor?: number, sync3d = true) => {
    if (!project || row.kind !== 'template') return
    const template = project.templates.find(item => item.id === row.templateId)
    if (!template || row.sequence[column] === '-') return
    const selectedColumns = selection[row.id]?.columns || []
    const anchor = explicitAnchor ?? selection[row.id]?.anchor ?? column
    const mode = event.shiftKey ? 'extend' : event.ctrlKey || event.metaKey || event.altKey ? 'toggle' : 'replace'
    const ordered = updateColumnSelection(selectedColumns, row.sequence, column, anchor, mode)
    setSelection(currentSelection => ({ ...currentSelection, [row.id]: { anchor: column, columns: ordered } }))
    if (!sync3d || !selectionSyncEnabled) return
    try {
      await loadTemplateInPrimary(template)
      let residueIndex = 0
      const residues = ordered.map(alignmentColumn => {
        residueIndex = row.sequence.slice(0, alignmentColumn + 1).replace(/-/g, '').length
        return { chainId: template.chain, seqId: residueIndex }
      })
      useSelectionStore.getState().select(residues, 'sequence')
    } catch (reason: any) { setError(reason.message || String(reason)) }
  }

  const moveGap = (groupIndex: number, row: AlignmentRow, direction: -1 | 1) => {
    const column = selection[row.id]?.anchor ?? row.sequence.indexOf('-')
    const other = column + direction
    if (column < 0 || other < 0 || other >= row.sequence.length || row.sequence[column] !== '-' || row.sequence[other] === '-') return
    const chars = row.sequence.split(''); [chars[column], chars[other]] = [chars[other], chars[column]]
    editRow(groupIndex, row.id, chars.join(''))
    setSelection(current => ({ ...current, [row.id]: { anchor: other, columns: [other] } }))
  }

  const applySelectionAsModelingSpan = (groupIndex: number, row: AlignmentRow) => {
    if (!project || row.kind !== 'template') return
    const columns = (selection[row.id]?.columns || []).filter(column => row.sequence[column] !== '-')
    if (!columns.length) return
    const next = cloneGroups(project.alignmentGroups)
    next[groupIndex].masks[row.id] = alignmentColumnsToSpans(columns)
    next[groupIndex].maskModes = { ...(next[groupIndex].maskModes || {}), [row.id]: 'ranges' }
    commitGroups(next)
  }

  const addGapColumn = (groupIndex: number, column: number) => {
    if (!project) return
    const next = cloneGroups(project.alignmentGroups)
    next[groupIndex].rows = next[groupIndex].rows.map(row => ({ ...row, sequence: `${row.sequence.slice(0, column)}-${row.sequence.slice(column)}` }))
    for (const key of Object.keys(next[groupIndex].masks)) next[groupIndex].masks[key] = next[groupIndex].masks[key].map(span => ({
      start: span.start >= column ? span.start + 1 : span.start,
      end: span.end > column ? span.end + 1 : span.end,
    }))
    commitGroups(next)
  }

  const removeGapColumn = (groupIndex: number, column: number) => {
    if (!project || !project.alignmentGroups[groupIndex].rows.every(row => row.sequence[column] === '-')) return
    const next = cloneGroups(project.alignmentGroups)
    next[groupIndex].rows = next[groupIndex].rows.map(row => ({ ...row, sequence: row.sequence.slice(0, column) + row.sequence.slice(column + 1) }))
    for (const key of Object.keys(next[groupIndex].masks)) next[groupIndex].masks[key] = next[groupIndex].masks[key].map(span => ({
      start: span.start > column ? span.start - 1 : span.start,
      end: span.end > column ? span.end - 1 : span.end,
    })).filter(span => span.end > span.start)
    commitGroups(next)
  }

  const callProjectAction = async (action: 'align' | 'salign') => {
    if (!project) return
    setBusy(action === 'align' ? 'Generating alignment' : 'Structural alignment')
    setError('')
    setMessage('')
    try {
      const response = await apiFetch(`/api/homology/${action}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...project, workspaceId: activeWorkspace?.id }),
      })
      const body = await response.json() as HomologyProject & { error?: string }
      if (!response.ok) throw new Error(body.error || `HTTP ${response.status}`)
      setProject(body)
      setSaved(true)
      if (action === 'align') { setTab(2); setUndo([]); setRedo([]) }
      setMessage(action === 'align' ? 'Alignment generated' : 'Templates were structurally fitted within each target-chain group')
    } catch (reason: any) {
      setError(reason.message || String(reason))
    } finally {
      setBusy('')
    }
  }

  const commitGroups = (next: AlignmentGroup[]) => {
    if (!project) return
    setUndo(history => [...history.slice(-49), cloneGroups(project.alignmentGroups)])
    setRedo([])
    update({ alignmentGroups: next })
  }

  useEffect(() => {
    if (!selectionSyncEnabled || !project || tab !== 2 || !primaryFile || !activeTargetChain) return
    const groupIndex = project.alignmentGroups.findIndex(group => group.chainId === activeTargetChain)
    if (groupIndex < 0) return
    const group = project.alignmentGroups[groupIndex]
    const template = project.templates.find(item => item.file === primaryFile && item.targetChain === activeTargetChain)
    if (!template) return
    const row = group.rows.find(item => item.templateId === template.id)
    if (!row) return
    const selectedOrdinals = new Set([...selected3dResidues.values()].filter(item => item.chainId === template.chain).map(item => item.seqId))
    const columns = alignmentColumnsForResidues(row.sequence, selectedOrdinals)
    setSelection(current => {
      const previous = current[row.id]
      if (!columns.length) {
        if (!previous) return current
        const next = { ...current }
        delete next[row.id]
        return next
      }
      if (previous?.anchor === columns[columns.length - 1] && previous.columns.length === columns.length && previous.columns.every((value, index) => value === columns[index])) return current
      return { ...current, [row.id]: { anchor: columns[columns.length - 1], columns } }
    })
  // Selection synchronization intentionally tracks the active structure and workflow snapshot.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected3dResidues, primaryFile, activeTargetChain, selectionSyncEnabled, tab])

  const editRow = (groupIndex: number, rowId: string, sequence: string) => {
    if (!project) return
    const original = project.alignmentGroups[groupIndex].rows.find(row => row.id === rowId)
    if (!original || sequence.replace(/-/g, '') !== original.sequence.replace(/-/g, '')) {
      setError('Alignment editing may move gaps but cannot change the underlying amino-acid sequence. Edit residues in Target instead.')
      return
    }
    setError('')
    const next = cloneGroups(project.alignmentGroups)
    next[groupIndex].rows = next[groupIndex].rows.map(row => row.id === rowId ? { ...row, sequence: sequence.toUpperCase() } : row)
    if (next[groupIndex].maskModes?.[rowId] === 'ranges') {
      const oldColumns = new Set<number>()
      for (const span of next[groupIndex].masks[rowId] || []) for (let column = span.start; column < span.end; column++) oldColumns.add(column)
      const selectedOrdinals = new Set<number>()
      let ordinal = 0
      for (let column = 0; column < original.sequence.length; column++) {
        if (original.sequence[column] !== '-') { ordinal++; if (oldColumns.has(column)) selectedOrdinals.add(ordinal) }
      }
      const columns: number[] = []
      ordinal = 0
      for (let column = 0; column < sequence.length; column++) {
        if (sequence[column] !== '-') { ordinal++; if (selectedOrdinals.has(ordinal)) columns.push(column) }
      }
      const spans: AlignmentSpan[] = []
      for (const column of columns) {
        const last = spans[spans.length - 1]
        if (last?.end === column) last.end = column + 1
        else spans.push({ start: column, end: column + 1 })
      }
      next[groupIndex].masks[rowId] = spans
    }
    commitGroups(next)
  }

  const undoAlignment = () => {
    if (!project || !undo.length) return
    const previous = undo[undo.length - 1]
    setUndo(undo.slice(0, -1))
    setRedo(history => [...history, cloneGroups(project.alignmentGroups)])
    update({ alignmentGroups: previous })
  }

  const redoAlignment = () => {
    if (!project || !redo.length) return
    const next = redo[redo.length - 1]
    setRedo(redo.slice(0, -1))
    setUndo(history => [...history, cloneGroups(project.alignmentGroups)])
    update({ alignmentGroups: next })
  }

  const exportAlignment = () => {
    if (!project) return
    const text = project.alignmentGroups.flatMap(group => group.rows.map(row => (
      `>${group.chainId}|${row.id}\n${row.sequence}\n`
    ))).join('')
    const url = URL.createObjectURL(new Blob([text], { type: 'text/plain' }))
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `${project.name.replace(/[^a-zA-Z0-9_-]+/g, '_') || 'homology'}_alignment.fasta`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  const importAlignment = async (file: File | undefined) => {
    if (!project || !file) return
    try {
      const imported = new Map<string, string>()
      let key = ''
      for (const raw of (await file.text()).split(/\r?\n/)) {
        const line = raw.trim()
        if (!line) continue
        if (line.startsWith('>')) {
          key = line.slice(1).split(/\s+/)[0]
          imported.set(key, '')
        } else if (key) imported.set(key, `${imported.get(key) || ''}${line.toUpperCase()}`)
      }
      const next = cloneGroups(project.alignmentGroups)
      for (const group of next) {
        for (const row of group.rows) {
          const sequence = imported.get(`${group.chainId}|${row.id}`)
          if (!sequence) throw new Error(`Imported alignment is missing ${group.chainId}|${row.id}`)
          if (sequence.replace(/-/g, '') !== row.sequence.replace(/-/g, '')) {
            throw new Error(`Imported alignment changes the ungapped sequence of ${row.id}`)
          }
          row.sequence = sequence
        }
        if (new Set(group.rows.map(row => row.sequence.length)).size !== 1) {
          throw new Error(`Imported rows for target chain ${group.chainId} have different lengths`)
        }
        group.masks = {}
        group.maskModes = Object.fromEntries(group.rows.filter(row => row.kind === 'template').map(row => [row.id, 'all']))
      }
      commitGroups(next)
    } catch (reason: any) {
      setError(reason.message || String(reason))
    } finally {
      if (alignmentImportRef.current) alignmentImportRef.current.value = ''
    }
  }

  const runModel = async () => {
    if (!project) return
    const backend = project.modelOptions['--backend'] === 'diffusion' ? 'diffusion' : 'modeller'
    setBusy(backend === 'diffusion' ? 'Running mosaic diffusion' : 'Running Modeller')
    setError('')
    setMessage('')
    try {
      const response = await apiFetch('/api/homology/model', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...project, workspaceId: activeWorkspace?.id }),
      })
      const body = await response.json() as { error?: string; outputFile?: string; stderr?: string; modelStatus?: string }
      if (!response.ok) throw new Error(body.error || body.stderr || `HTTP ${response.status}`)
      setMessage(`${body.modelStatus && body.modelStatus !== 'success' ? 'Rejected candidate published' : 'Model complete'}: ${body.outputFile}`)
      await reloadWorkspace()
    } catch (reason: any) {
      setError(reason.message || String(reason))
    } finally {
      setBusy('')
    }
  }

  const setModelBackend = (backend: string) => {
    if (!project) return
    const options: Record<string, string | number | boolean> = {
      ...project.modelOptions,
      '--backend': backend,
    }
    if (backend === 'modeller') {
      delete options['--diffusion-model']
      delete options['--diffusion-seed']
    }
    update({ modelOptions: options })
  }

  if (!project) return <Box sx={{ p: 2 }}><CircularProgress size={20} /> {busy || 'Loading homology workspace…'}</Box>

  return (
    <Box sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <Box sx={projectToolbarSx}>
        <FormControl size="small" sx={{ width: 220, minWidth: 220 }}>
          <InputLabel>Project</InputLabel>
          <Select label="Project" value={project.id} onChange={event => loadProject(event.target.value)}>
            {projects.map(item => <MenuItem key={item.id} value={item.id}>{item.name}</MenuItem>)}
          </Select>
        </FormControl>
        <TextField size="small" sx={{ width: 220 }} label="Project name" value={project.name} onChange={event => update({ name: event.target.value })} />
        <Tooltip title="New project"><IconButton onClick={createProject}><AddIcon /></IconButton></Tooltip>
        <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>{saved ? 'Saved' : 'Saving…'}</Typography>
      </Box>
      <Tabs value={tab} onChange={(_event, value) => setTab(value)} sx={{ minHeight: 30, borderBottom: 1, borderColor: 'divider', '& .MuiTab-root': { minHeight: 30, py: 0.25, px: 1.25, fontSize: '0.72rem', textTransform: 'none' } }}>
        <Tab label="1. Target" /><Tab label="2. Templates" /><Tab label="3. Alignment" /><Tab label="4. Model" />
      </Tabs>
      <Box sx={{ flex: 1, overflow: 'auto', p: 1.5 }}>
        {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
        {message && <Alert severity="success" sx={{ mb: 1 }}>{message}</Alert>}
        {busy && <Alert severity="info" icon={<CircularProgress size={16} />} sx={{ mb: 1 }}>{busy}</Alert>}

        {tab === 0 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Typography variant="body2">Enter one FASTA record per target chain. Sequence residues are edited here; the alignment tab edits gaps only.</Typography>
            <Box sx={homologyToolbarSx}>
              <FormControl size="small" sx={targetSourceControlSx}><InputLabel>Workspace file</InputLabel>
                <Select label="Workspace file" value={targetSource} onChange={event => setTargetSource(event.target.value)}>
                  {artifacts.map(item => <MenuItem key={item.file} value={item.file}>{item.name || item.file} · {item.file}</MenuItem>)}
                </Select>
              </FormControl>
              <Tooltip title={targetSource && !targetSourceSupported ? 'This file type does not contain a supported protein sequence' : 'Parse protein sequences into Target FASTA'}>
                <Box component="span" sx={toolbarTooltipWrapperSx}><Button sx={primaryActionSx} variant="outlined" onClick={parseTargetSource} disabled={!targetSource || !targetSourceSupported || busy !== ''}>Parse sequence</Button></Box>
              </Tooltip>
            </Box>
            {!!parsePreview.length && <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1 }}>
              <Typography variant="subtitle2" sx={{ mb: 0.5 }}>Parsed sequences</Typography>
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                Target FASTA was populated immediately. Adjust included chains or IDs below, then apply the corrections.
              </Typography>
              {parsePreview.map((record, index) => <Box key={index} sx={{ display: 'grid', gridTemplateColumns: '36px minmax(160px, 1fr) 100px', gap: 1, alignItems: 'center', mb: 0.5 }}>
                <Checkbox size="small" checked={record.selected} onChange={event => setParsePreview(current => current.map((item, itemIndex) => itemIndex === index ? { ...item, selected: event.target.checked } : item))} />
                <TextField size="small" label="Target/chain ID" value={record.id} onChange={event => setParsePreview(current => current.map((item, itemIndex) => itemIndex === index ? { ...item, id: event.target.value } : item))} />
                <Typography variant="caption">{record.length} aa</Typography>
              </Box>)}
              <Box sx={{ display: 'flex', gap: 1, mt: 1 }}><Button variant="contained" size="small" onClick={applyParsedTarget}>Apply corrections</Button><Button size="small" onClick={() => setParsePreview([])}>Close preview</Button></Box>
            </Box>}
            <TextField multiline minRows={12} label="Target FASTA" value={project.targetFasta}
              onChange={event => update({ targetFasta: event.target.value, alignmentGroups: [] })}
              slotProps={{ htmlInput: { spellCheck: false } }}
              sx={{ '& textarea': { fontFamily: 'ui-monospace, monospace' } }} />
            <Typography variant="caption">Detected chains: {targetChains.join(', ') || 'none'}</Typography>
          </Box>
        )}

        {tab === 1 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Box sx={homologyToolbarSx}>
              <Button startIcon={<AddIcon />} variant="outlined" onClick={addTemplate}>Add new</Button>
              <FormControl size="small" sx={toolbarControlSx}>
                <InputLabel>Target chain</InputLabel>
                <Select label="Target chain" value={activeTargetChain} disabled={!targetChains.length}
                  onChange={event => setActiveTargetChain(event.target.value)}>
                  {targetChains.map(chain => <MenuItem key={chain} value={chain}>{chain}</MenuItem>)}
                </Select>
              </FormControl>
              <Button startIcon={<AccountTreeIcon />} variant="outlined" onClick={() => callProjectAction('salign')} disabled={busy !== '' || project.templates.length < 2}>Structural align</Button>
              <Button sx={primaryActionSx} variant="contained" onClick={() => callProjectAction('align')} disabled={busy !== '' || !targetChains.length || !project.templates.length}>Generate MSA</Button>
              <FormControl size="small" sx={toolbarControlSx}>
                <InputLabel>MSA engine</InputLabel>
                <Select label="MSA engine" value={project.engine} onChange={event => update({ engine: event.target.value as HomologyProject['engine'] })}>
                  <MenuItem value="mafft" disabled={engines.mafft?.available === false}>MAFFT{engines.mafft?.available === false ? ' (missing)' : ''}</MenuItem>
                  <MenuItem value="muscle" disabled={engines.muscle?.available === false}>MUSCLE 5{engines.muscle?.available === false ? ' (missing)' : ''}</MenuItem>
                  <MenuItem value="clustalo" disabled={engines.clustalo?.available === false}>Clustal Omega{engines.clustalo?.available === false ? ' (missing)' : ''}</MenuItem>
                </Select>
              </FormControl>
            </Box>
            {visibleTemplates.map(template => (
              <Box key={template.id} sx={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 1fr) minmax(180px, 260px) 40px', gap: 1, alignItems: 'center' }}>
                <FormControl size="small"><InputLabel>Structure</InputLabel><Select label="Structure" value={template.file} onChange={event => changeTemplateFile(template, event.target.value)}>
                  {artifacts.filter(item => item.kind === 'structure').map(item => <MenuItem key={item.file} value={item.file}>{item.name || item.file}</MenuItem>)}
                </Select></FormControl>
                <FormControl size="small"><InputLabel>Chain</InputLabel><Select label="Chain" value={template.chain} onChange={event => updateTemplate(template.id, { chain: event.target.value })}>
                  {(chainsByFile[template.file] || []).map(chain => <MenuItem key={chain.id} value={chain.id}>
                    {chainIdentityLabel(chain.id, chain.length, targetSequenceByChain[template.targetChain] || '', chain.sequence)}
                  </MenuItem>)}
                </Select></FormControl>
                <IconButton onClick={() => update({ templates: project.templates.filter(item => item.id !== template.id) })}><DeleteIcon /></IconButton>
              </Box>
            ))}
          </Box>
        )}

        {tab === 2 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            <Box sx={{
              ...homologyToolbarSx,
              minHeight: 27,
              py: 0,
              '& .MuiButton-root': { ...homologyToolbarSx['& .MuiButton-root'], height: 24 },
              '& .MuiIconButton-root': { ...homologyToolbarSx['& .MuiIconButton-root'], width: 24, height: 24 },
              '& .MuiInputBase-root': { height: 24 },
              '& .MuiInputLabel-root:not(.MuiInputLabel-shrink)': { transform: 'translate(14px, 1px) scale(1)' },
              '& .MuiSelect-select, & .MuiInputBase-input': { py: '1px' },
            }}>
              <input ref={alignmentImportRef} hidden type="file" accept=".fasta,.fa,.faa,.aln" onChange={event => importAlignment(event.target.files?.[0])} />
              {targetChains.length > 1 && <FormControl size="small" sx={{ minWidth: 180 }}><InputLabel>Target chain</InputLabel>
                <Select label="Target chain" value={activeTargetChain} onChange={event => setActiveTargetChain(event.target.value)}>
                  {targetChains.map(chain => <MenuItem key={chain} value={chain}>{chain}</MenuItem>)}
                </Select>
              </FormControl>}
              <Tooltip title="Undo alignment edit"><span><IconButton disabled={!undo.length} onClick={undoAlignment}><UndoIcon /></IconButton></span></Tooltip>
              <Tooltip title="Redo alignment edit"><span><IconButton disabled={!redo.length} onClick={redoAlignment}><RedoIcon /></IconButton></span></Tooltip>
              <Tooltip title={selectionSyncEnabled ? 'Alignment and 3D residue selections are linked; click to unlock' : 'Alignment and 3D residue selections are independent; click to link'}>
                <IconButton onClick={() => setSelectionSyncEnabled(enabled => !enabled)} color={selectionSyncEnabled ? 'primary' : 'default'}>
                  {selectionSyncEnabled ? <LinkIcon /> : <LinkOffIcon />}
                </IconButton>
              </Tooltip>
              <Button onClick={() => callProjectAction('align')} disabled={busy !== ''}>Reset from {project.engine}</Button>
              <Button onClick={() => alignmentImportRef.current?.click()}>Import aligned FASTA</Button>
              <Button onClick={exportAlignment} disabled={!project.alignmentGroups.length}>Export alignment</Button>
            </Box>
            {!project.alignmentGroups.length && <Alert severity="info">Generate an alignment from the Templates tab.</Alert>}
            {project.alignmentGroups.map((group, groupIndex) => {
              if (group.chainId !== activeTargetChain) return null
              const lengths = new Set(group.rows.map(row => row.sequence.length))
              const consensus = consensusFor(group.rows)
              const reference = group.rows.find(row => row.kind === 'target')?.sequence || ''
              const activeColumn = Object.values(selection)[0]?.anchor ?? 0
              return (
                <Box key={group.chainId} sx={{ border: 1, borderColor: lengths.size === 1 ? 'divider' : 'error.main', borderRadius: 1 }}>
                  <Box sx={{ px: 1, py: 0.75, display: 'flex', alignItems: 'center', gap: 1, borderBottom: 1, borderColor: 'divider' }}>
                    <Typography variant="subtitle2">Target chain {group.chainId} · {group.rows[0]?.sequence.length || 0} columns</Typography>
                    <Button size="small" onClick={() => addGapColumn(groupIndex, activeColumn)}>Add gap column</Button>
                    <Button size="small" onClick={() => removeGapColumn(groupIndex, activeColumn)}
                      disabled={!group.rows.every(row => row.sequence[activeColumn] === '-')}>Remove all-gap column</Button>
                  </Box>
                  {lengths.size !== 1 && <Alert severity="warning" sx={{ mb: 1 }}>Rows must have equal lengths before modeling.</Alert>}
                  <Box sx={{ overflowX: 'auto', overflowY: 'hidden', fontFamily: 'ui-monospace, "Cascadia Mono", monospace', userSelect: 'none' }}>
                    <Box sx={{ minWidth: 'max-content', py: 1 }}>
                      <AlignmentCells label="consensus" sequence={consensus} annotation />
                      {group.rows.map(row => {
                        const masks = group.masks[row.id] || []
                        const template = row.kind === 'template'
                          ? project.templates.find(item => item.id === row.templateId)
                          : undefined
                        const sourceName = template?.file.split('/').pop() || template?.label || row.id
                        const rowLabel = row.kind === 'target' ? `target: ${row.id}` : `template: ${sourceName}`
                        return <Box key={row.id} sx={{ mb: 1.5 }}>
                          {row.kind === 'template' && <AlignmentCells label={<Box sx={{ display: 'flex', gap: 0.5, alignItems: 'center' }}>
                            <Button size="small" onClick={() => { const next = cloneGroups(project.alignmentGroups); next[groupIndex].masks[row.id] = []; next[groupIndex].maskModes = { ...(next[groupIndex].maskModes || {}), [row.id]: 'all' }; commitGroups(next) }}>Select all</Button>
                            <Button size="small" onClick={() => { const next = cloneGroups(project.alignmentGroups); next[groupIndex].masks[row.id] = []; next[groupIndex].maskModes = { ...(next[groupIndex].maskModes || {}), [row.id]: 'none' }; commitGroups(next) }}>Clear</Button>
                            <Button size="small" disabled={!selection[row.id]?.columns.length} onClick={() => applySelectionAsModelingSpan(groupIndex, row)}>Use selection as modeling span</Button>
                          </Box>} sequence={comparisonToReference(reference, row.sequence)} annotation />}
                          <Box sx={{ display: 'flex', alignItems: 'center', minWidth: 'max-content' }}>
                            <Box sx={{ position: 'sticky', left: 0, zIndex: 2, bgcolor: 'background.paper', width: ALIGNMENT_LABEL_WIDTH, flexShrink: 0, px: 1, display: 'flex', alignItems: 'center', gap: 0.25, overflow: 'hidden' }}>
                              <Chip size="small" color={row.kind === 'target' ? 'primary' : 'default'} label={rowLabel} sx={{ maxWidth: 220 }} />
                              <Tooltip title="Move selected gap left"><span><Button size="small" sx={{ minWidth: 24, px: 0.25 }} onClick={() => moveGap(groupIndex, row, -1)}>←</Button></span></Tooltip>
                              <Tooltip title="Move selected gap right"><span><Button size="small" sx={{ minWidth: 24, px: 0.25 }} onClick={() => moveGap(groupIndex, row, 1)}>→</Button></span></Tooltip>
                            </Box>
                            {Array.from(row.sequence).map((character, column) => {
                              const mode = group.maskModes?.[row.id] || (masks.length ? 'ranges' : 'all')
                              const modelSelected = row.kind === 'template' && (mode === 'all' ? character !== '-' : mode === 'ranges' && masks.some(mask => column >= mask.start && column < mask.end))
                              const transientSelected = selection[row.id]?.columns.includes(column) === true
                              const comparison = row.kind === 'template' ? comparisonToReference(reference, row.sequence)[column] : '*'
                              const targetMatch = row.kind === 'template' && comparison === '*'
                              const color = character === '-' ? '#9e9e9e' : RESIDUE_CLASS_COLORS[residueClass(character)]
                              return <Tooltip key={column} title={`${rowLabel} · column ${column + 1}`}>
                                <Box component="button" onMouseDown={event => {
                                  event.preventDefault()
                                  if (row.kind !== 'template') setSelection(current => ({ ...current, [row.id]: { anchor: column, columns: [column] } }))
                                  if (row.kind === 'template' && character !== '-') {
                                    alignmentDragRef.current = { groupIndex, rowId: row.id, anchor: column, moved: false }
                                    selectTemplateColumns(row, column, event, undefined, true).catch(() => {})
                                  }
                                }} onMouseEnter={event => {
                                  const drag = alignmentDragRef.current
                                  if (row.kind !== 'template' || character === '-' || !drag || drag.groupIndex !== groupIndex || drag.rowId !== row.id || !(event.buttons & 1)) return
                                  drag.moved = true
                                  selectTemplateColumns(row, column, { shiftKey: true, ctrlKey: false, metaKey: false, altKey: false }, drag.anchor, false).catch(() => {})
                                }} onMouseUp={() => {
                                  const drag = alignmentDragRef.current
                                  if (row.kind !== 'template' || !drag || drag.groupIndex !== groupIndex || drag.rowId !== row.id) return
                                  alignmentDragRef.current = null
                                  if (drag.moved) selectTemplateColumns(row, column, { shiftKey: true, ctrlKey: false, metaKey: false, altKey: false }, drag.anchor, true).catch(() => {})
                                }} sx={{ width: 16, height: 22, p: 0, border: 0, borderBottom: selection[row.id]?.anchor === column ? '2px solid' : comparison === '×' ? '2px solid #ef5350' : '2px solid transparent', borderColor: selection[row.id]?.anchor === column ? 'primary.main' : undefined, bgcolor: modelSelected ? 'primary.main' : targetMatch ? '#f7fbf3' : comparison === '×' ? '#ffebee' : character === '-' ? 'grey.100' : 'transparent', color: modelSelected ? 'primary.contrastText' : color, boxShadow: transientSelected ? 'inset 0 0 0 2px #263f78' : 'none', fontWeight: targetMatch ? 800 : comparison === '×' ? 600 : 500, fontFamily: 'inherit', fontSize: 12, cursor: character === '-' ? 'default' : 'pointer' }}>{character}</Box>
                              </Tooltip>
                            })}
                          </Box>
                        </Box>
                      })}
                    </Box>
                  </Box>
                </Box>
              )
            })}
          </Box>
        )}

        {tab === 3 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
            <Box sx={homologyToolbarSx}>
              <FormControl size="small" sx={toolbarControlSx}><InputLabel>Backend</InputLabel><Select label="Backend" value={project.modelOptions['--backend'] ?? 'modeller'}
                onChange={event => setModelBackend(String(event.target.value))}>
                <MenuItem value="modeller">Modeller</MenuItem><MenuItem value="diffusion">Diffusion</MenuItem>
              </Select></FormControl>
              {(project.modelOptions['--backend'] ?? 'modeller') === 'modeller' ? <>
                <TextField sx={toolbarControlSx} size="small" type="number" label="Models" value={project.modelOptions['--num-models'] ?? 5}
                  onChange={event => update({ modelOptions: { ...project.modelOptions, '--num-models': Number(event.target.value) } })} />
                <FormControl size="small" sx={toolbarControlSx}><InputLabel>MD refinement</InputLabel><Select label="MD refinement" value={project.modelOptions['--md-level'] ?? 'fast'}
                  onChange={event => update({ modelOptions: { ...project.modelOptions, '--md-level': event.target.value } })}>
                  {['none', 'fast', 'slow', 'very_slow', 'slow_large'].map(level => <MenuItem key={level} value={level}>{level}</MenuItem>)}
                </Select></FormControl>
              </> : <>
                <FormControl size="small" sx={toolbarControlSx}><InputLabel>Diffusion model</InputLabel>
                  <Select label="Diffusion model" value={project.modelOptions['--diffusion-model'] ?? ''}
                    onChange={event => update({ modelOptions: { ...project.modelOptions, '--diffusion-model': event.target.value } })}>
                    <MenuItem value="">Auto</MenuItem><MenuItem value="protenix">Protenix</MenuItem><MenuItem value="protpardelle">Protpardelle</MenuItem>
                  </Select>
                </FormControl>
                <TextField sx={toolbarControlSx} size="small" type="number" label="Seed" value={project.modelOptions['--diffusion-seed'] ?? 7}
                  onChange={event => update({ modelOptions: { ...project.modelOptions, '--diffusion-seed': Number(event.target.value) } })} />
              </>}
              <Button sx={primaryActionSx} variant="contained"
                onClick={runModel} disabled={busy !== '' || !project.alignmentGroups.length}>Run {(project.modelOptions['--backend'] ?? 'modeller') === 'diffusion' ? 'Diffusion' : 'Modeller'}</Button>
            </Box>
            <Typography variant="caption" color="text.secondary">
              Selected spans are assembled from the fitted structures into one coordinate-preserving mosaic template. At overlapping columns, the earlier template in the Templates tab has precedence. Diffusion keeps covered matching residues fixed and generates only admitted uncovered regions; it never falls back to Modeller.
            </Typography>
          </Box>
        )}
      </Box>
    </Box>
  )
}
