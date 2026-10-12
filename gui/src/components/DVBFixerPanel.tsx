import { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Tabs from '@mui/material/Tabs'
import Tab from '@mui/material/Tab'
import Button from '@mui/material/Button'
import Checkbox from '@mui/material/Checkbox'
import TextField from '@mui/material/TextField'
import FormControl from '@mui/material/FormControl'
import FormControlLabel from '@mui/material/FormControlLabel'
import InputLabel from '@mui/material/InputLabel'
import Select from '@mui/material/Select'
import MenuItem from '@mui/material/MenuItem'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import Divider from '@mui/material/Divider'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import RefreshIcon from '@mui/icons-material/Refresh'
import CancelIcon from '@mui/icons-material/CancelOutlined'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import { useStructureStore } from '../stores/structureStore'
import { alignSequences, chainToSequence } from '../lib/alignment'
import { filterSequenceableChains } from '../lib/chain-grouping'
import { useWorkspaceStore, workspaceFileUrl } from '../stores/workspaceStore'
import { createManagedJobRequest, isActiveManagedJob, managedJobStatusLabel, selectRestoredManagedJob, type ManagedJobRecord } from '../lib/managed-jobs'
import { structureMetaFromArtifact } from '../lib/workspace-metadata'
import { apiFetch, apiSse } from '../lib/api-client'
import { v1Client } from '../lib/v1-client'
import { workflowOptionActive, workflowValues } from '../lib/workflow-backend-options'

// Re-declare the spec types here (mirrors server/dvbfixer-spec.ts) so the
// frontend doesn't have to import server/. The actual spec is fetched at
// runtime from /api/dvbfixer-spec.
interface FlagDef {
  flag: string
  dest: string
  label: string
  type: 'bool' | 'number' | 'text' | 'select' | 'artifact'
  group: string
  default?: string | number | boolean | Array<string | number>
  options?: Array<string | number>
  min?: number
  max?: number
  step?: number
  help?: string
  required?: boolean
  repeatable?: boolean
  multi?: boolean
  falseFlag?: string
  exclusiveGroup?: string
  name?: string
  nargs?: string | number | null
}
interface CommandDef {
  name: string
  label: string
  description: string
  category: string
  inputs: FlagDef[]
  flags: FlagDef[]
  groups: Array<{ name: string; fields: string[] }>
  outputExtension: string
  outputMode: 'file' | 'prefix' | 'directory' | 'stdout'
  hasOutput: boolean
  batch: boolean
  successCodes: number[]
  specialized?: boolean
}

interface StructureEntry {
  id: string
  file: string
  name: string
  kind?: string
  artifactType?: string
}

interface RunResult {
  ok: boolean
  command: string
  outputFile: string
  outputDir: string
  /** When the run failed, the output folder is moved here (relative to structures/). */
  movedTo?: string | null
  stdout: string
  stderr: string
  exitCode: number
}

/**
 * Multiline text input with an inline overlay that colors SEQRES-only
 * residues greyed + italic — matches the Sequence panel's missing-residue
 * style. Used by the DVBFixer model tab's per-chain FASTA boxes.
 *
 * Underlay is a non-interactive `<div>` rendered absolutely under a
 * transparent-text `<textarea>` (caret stays visible via caretColor).
 * Both layers share identical font/padding/wrap rules — alignment is
 * pixel-perfect by construction.
 *
 * Highlighting is gated on `value === parsedSequence`. Edit a single
 * character → the whole box reverts to plain text so user-typed
 * characters can never be mis-classified as "missing from structure".
 * Re-parse → highlighting returns.
 */
interface HighlightedFastaInputProps {
  value: string
  onChange: (v: string) => void
  label: string
  placeholder?: string
  parsedSequence?: string
  presentMap?: boolean[]
  minRows?: number
}
function HighlightedFastaInput({
  value, onChange, label, placeholder,
  parsedSequence, presentMap, minRows = 3,
}: HighlightedFastaInputProps) {
  const editorRef = useRef<HTMLTextAreaElement>(null)
  const underlayRef = useRef<HTMLDivElement>(null)
  const biologicalValue = value.replace(/\s+/g, '')
  const [coverageMap, setCoverageMap] = useState<boolean[] | undefined>(presentMap)
  useEffect(() => {
    if (parsedSequence === undefined || presentMap === undefined) {
      setCoverageMap(undefined)
      return
    }
    if (biologicalValue.length === parsedSequence.length) {
      setCoverageMap(presentMap)
      return
    }
    // Affine alignment is O(m*n). Debounce ordinary edits and decline very
    // large matrices instead of freezing the form.
    if (biologicalValue.length * parsedSequence.length > 250_000) {
      setCoverageMap(undefined)
      return
    }
    const timer = window.setTimeout(() => {
      const aligned = alignSequences(biologicalValue.toUpperCase(), parsedSequence.toUpperCase())
      const mapped: boolean[] = []
      let parsedIndex = 0
      for (let column = 0; column < aligned.length; column++) {
        const edited = aligned.alignedA[column]
        const parsed = aligned.alignedB[column]
        if (edited !== '-') {
          mapped.push(parsed === '-' ? false : presentMap[parsedIndex] !== false)
        }
        if (parsed !== '-') parsedIndex++
      }
      setCoverageMap(mapped)
    }, 180)
    return () => window.clearTimeout(timer)
  }, [biologicalValue, parsedSequence, presentMap])
  const isHighlighted = coverageMap !== undefined
  const onScroll = useCallback(() => {
    if (underlayRef.current && editorRef.current) {
      underlayRef.current.scrollTop = editorRef.current.scrollTop
    }
  }, [])
  const FONT = 'ui-monospace, monospace'
  const FONT_SIZE = '0.7rem'
  const LINE_HEIGHT = 1.5
  const PADDING = '6px 8px'
  // Approximate height = lineHeight * fontSize * rows + vertical padding.
  // 0.7rem ≈ 11.2px → row ≈ 16.8px; minRows=3 → ~50px content + 12px pad.
  const contentHeight = `calc(${LINE_HEIGHT}em * ${minRows})`
  return (
    <Box sx={{
      position: 'relative',
      border: 1, borderColor: 'divider', borderRadius: 1,
      pt: 1.25, px: 1, pb: 0.5,
      transition: 'border-color 120ms',
      '&:focus-within': { borderColor: 'primary.main' },
    }}>
      <Typography
        variant="caption"
        sx={{
          position: 'absolute', top: -7, left: 8,
          px: 0.5, bgcolor: 'background.paper',
          fontSize: '0.65rem', color: 'text.secondary',
          pointerEvents: 'none',
        }}
      >
        {label}
      </Typography>
      <Box sx={{ position: 'relative', height: contentHeight }}>
        <Box
          ref={underlayRef}
          aria-hidden
          sx={{
            position: 'absolute', inset: 0,
            pointerEvents: 'none', overflow: 'hidden',
            fontFamily: FONT, fontSize: FONT_SIZE, lineHeight: LINE_HEIGHT,
            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            padding: PADDING,
            color: 'text.primary',
            boxSizing: 'border-box',
          }}
        >
          {isHighlighted
            ? (() => {
                let biologicalIndex = 0
                return Array.from(value).map((ch, i) => {
                  const index = /\s/.test(ch) ? -1 : biologicalIndex++
                  return (
                <span
                  key={i}
                  style={index >= 0 && coverageMap[index] === false
                    ? { color: '#b5bfcc', fontStyle: 'italic', fontWeight: 400 }
                    : undefined}
                >{ch}</span>
                  )
                })
              })()
            : value || (
                <span style={{ color: '#9ea7b3', fontStyle: 'italic' }}>
                  {placeholder ?? ''}
                </span>
              )}
        </Box>
        <textarea
          ref={editorRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onScroll={onScroll}
          spellCheck={false}
          style={{
            position: 'absolute', inset: 0,
            width: '100%', height: '100%',
            border: 'none', outline: 'none', resize: 'none',
            background: 'transparent', color: 'transparent',
            caretColor: '#1976d2',
            fontFamily: FONT, fontSize: FONT_SIZE, lineHeight: LINE_HEIGHT,
            padding: PADDING,
            whiteSpace: 'pre-wrap', wordBreak: 'break-all',
            boxSizing: 'border-box',
            margin: 0,
          }}
        />
      </Box>
    </Box>
  )
}

export function DVBFixerPanel() {
  const [commands, setCommands] = useState<CommandDef[]>([])
  const [tabIdx, setTabIdx] = useState(0)
  const [category, setCategory] = useState('')
  const [structures, setStructures] = useState<StructureEntry[]>([])
  const [inputFile, setInputFile] = useState<string>('')
  const [inputsByCommand, setInputsByCommand] = useState<Record<string, Record<string, string | string[]>>>({})
  const [values, setValues] = useState<Record<string, Record<string, any>>>({})
  const [job, setJob] = useState<ManagedJobRecord | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [result, setResult] = useState<RunResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const workspace = useWorkspaceStore(state => state.active)
  const workspaceRevision = useWorkspaceStore(state => state.revision)
  const reloadWorkspace = useWorkspaceStore(state => state.reload)
  const updateToolState = useWorkspaceStore(state => state.updateToolState)
  const terminalHandledRef = useRef<Set<string>>(new Set())
  const submitInFlightRef = useRef(false)

  const jobActive = isActiveManagedJob(job)
  const activeJobId = jobActive ? job?.id : undefined

  // Restore an interrupted/active run whenever this panel mounts or the
  // active workspace changes. The server is the source of truth.
  useEffect(() => {
    const workspaceId = workspace?.id
    setJob(null)
    setCancelling(false)
    if (!workspaceId) return
    const controller = new AbortController()
    v1Client.GET('/api/v1/workspaces/{workspaceId}/jobs', {
      params: { path: { workspaceId } }, signal: controller.signal, cache: 'no-store',
    })
      .then(({ data, error, response }) => {
        if (error) throw new Error(error.error.message || `Jobs: HTTP ${response.status}`)
        if (!data) throw new Error('Jobs response is not an array')
        const restored = selectRestoredManagedJob(data as ManagedJobRecord[])
        if (!restored || controller.signal.aborted) return
        // Historical terminal jobs are shown but must not auto-load again.
        if (!isActiveManagedJob(restored)) terminalHandledRef.current.add(restored.id)
        setJob(restored)
      })
      .catch(reason => { if (reason.name !== 'AbortError') setError(reason.message || String(reason)) })
    return () => controller.abort()
  }, [workspace?.id])

  // Stream state changes, with polling as a fallback for proxies where the
  // authenticated event stream is unavailable or disconnected.
  useEffect(() => {
    if (!activeJobId || !workspace?.id) return
    const workspaceId = workspace.id
    const jobId = activeJobId
    let disposed = false
    const streamController = new AbortController()
    const apply = (next: ManagedJobRecord) => {
      if (!disposed && next.id === jobId && next.workspaceId === workspaceId) setJob(next)
    }
    void (async () => {
      try {
        for await (const event of apiSse(
          `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/jobs/${encodeURIComponent(jobId)}/events`,
          { cache: 'no-store', signal: streamController.signal },
        )) {
          try { apply(JSON.parse(event.data) as ManagedJobRecord) } catch { /* polling remains available */ }
        }
      } catch { /* polling remains available */ }
    })()
    const poll = async () => {
      try {
        const { data } = await v1Client.GET('/api/v1/workspaces/{workspaceId}/jobs/{jobId}', {
          params: { path: { workspaceId, jobId } }, cache: 'no-store',
        })
        if (data) apply(data as ManagedJobRecord)
      } catch { /* the next poll or SSE event can recover */ }
    }
    const timer = window.setInterval(() => { void poll() }, 1500)
    void poll()
    return () => { disposed = true; streamController.abort(); window.clearInterval(timer) }
  }, [activeJobId, workspace?.id])

  // Fetch terminal logs for the existing output pane.
  useEffect(() => {
    if (!job || isActiveManagedJob(job) || !workspace?.id) return
    const controller = new AbortController()
    Promise.all([job.stdoutLog, job.stderrLog].map(async file => {
      const response = await apiFetch(workspaceFileUrl(workspace.id, file), { cache: 'no-store', signal: controller.signal })
      return response.ok ? response.text() : ''
    })).then(([stdout, stderr]) => {
      if (controller.signal.aborted) return
      setResult({
        ok: job.status === 'succeeded', command: [job.command, ...job.args].join(' '),
        outputFile: job.outputFile || '', outputDir: job.outputDir,
        stdout, stderr: stderr || job.error || '', exitCode: job.exitCode ?? -1,
      })
    }).catch(reason => { if (reason.name !== 'AbortError') setError(reason.message || String(reason)) })
    return () => controller.abort()
  }, [job, workspace?.id])

  // A newly-completed successful job registers artifacts server-side. Refresh
  // once and load its primary structure, without replaying historical jobs.
  useEffect(() => {
    if (!job || isActiveManagedJob(job) || terminalHandledRef.current.has(job.id) || !workspace?.id) return
    terminalHandledRef.current.add(job.id)
    setCancelling(false)
    const workspaceId = workspace.id
    ;(async () => {
      const refreshed = await reloadWorkspace()
      if (job.status !== 'succeeded' || !job.outputFile || !/\.(pdb|cif|mmcif|gro)$/i.test(job.outputFile)) return
      const plugin = useStructureStore.getState().plugin
      if (!plugin) return
      const response = await apiFetch(workspaceFileUrl(workspaceId, job.outputFile), { cache: 'no-store' })
      if (!response.ok) throw new Error(`Output cannot be loaded: HTTP ${response.status}`)
      const format = /\.(cif|mmcif)$/i.test(job.outputFile) ? 'mmcif' : 'pdb'
      await plugin.clear()
      const data = await plugin.builders.data.rawData({ data: await response.text(), label: job.outputFile })
      const trajectory = await plugin.builders.structure.parseTrajectory(data, format as any)
      await plugin.builders.structure.hierarchy.applyPreset(trajectory, 'default', {
        structure: { name: 'model', params: {} },
      })
      const artifact = refreshed?.artifacts.find(item => item.file === job.outputFile)
      if (artifact) useStructureStore.getState().setMeta(structureMetaFromArtifact(artifact))
      useStructureStore.getState().setFileName(job.outputFile)
      userPickedInputRef.current = false
      setInputFile(job.outputFile)
    })().catch(reason => setError(reason.message || String(reason)))
  }, [job, reloadWorkspace, workspace?.id])

  const fetchSpec = useCallback(() => {
    apiFetch(`/api/dvbfixer-spec?t=${Date.now()}`, { cache: 'no-store' })
      .then(r => r.ok ? r.json() : Promise.reject(`spec ${r.status}`))
      .then((data: CommandDef[]) => {
        setCommands(data)
        setCategory(current => current || data[0]?.category || '')
        setValues(prev => {
          // Preserve user-entered values per command; only fill in defaults
          // for newly-arrived commands.
          const next = { ...prev }
          for (const c of data) {
            if (!next[c.name]) {
              next[c.name] = {}
              for (const f of c.flags) {
                if (f.default !== undefined) next[c.name][f.flag] = f.default
              }
            } else {
              // Fill in defaults for any newly-added flags
              for (const f of c.flags) {
                if (next[c.name][f.flag] === undefined && f.default !== undefined) {
                  next[c.name][f.flag] = f.default
                }
              }
            }
          }
          return next
        })
      })
      .catch(() => {})
  }, [])

  useEffect(() => { fetchSpec() }, [fetchSpec])

  useEffect(() => {
    setStructures((workspace?.artifacts || []).filter(item => !item.hidden).map(item => ({ id: item.id, file: item.file, name: item.name, kind: item.kind, artifactType: item.artifactType })))
  }, [workspace, workspaceRevision])

  useEffect(() => {
    const state = workspace?.toolState?.dvbfixer as any
    if (!state) return
    setInputFile(state.inputFile || '')
    setInputsByCommand(state.inputsByCommand || {})
    setValues(current => ({ ...current, ...(state.values || {}) }))
    if (state.category) setCategory(state.category)
    if (state.result) setResult(state.result)
  // Restore once when switching workspaces; autosave updates must not reset in-progress edits.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspace?.id])

  useEffect(() => {
    if (!workspace) return
    updateToolState('dvbfixer', { inputFile, inputsByCommand, values, category, result })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [inputFile, inputsByCommand, values, category, result])

  // Keep the input dropdown in sync with the currently-loaded structure in
  // the PRIMARY 3D viewer. When the user loads / switches structures, the
  // DVBFixer input auto-updates to match. The user can still pick something
  // else from the dropdown manually.
  const primaryFileName = useStructureStore((s) => s.fileName)
  const userPickedInputRef = useRef(false)
  useEffect(() => {
    if (!primaryFileName) return
    // Only auto-sync if the user hasn't manually picked something different.
    if (!userPickedInputRef.current || inputFile === '') {
      setInputFile(primaryFileName)
    }
  }, [primaryFileName, inputFile])

  // Fallback default on first load if there's no primary structure: pick
  // a non-dvb root file.
  useEffect(() => {
    if (inputFile === '' && structures.length > 0 && !primaryFileName) {
      const pick = structures.find(d => !d.file.startsWith('dvb_')) ?? structures[0]
      setInputFile(pick.file)
    }
  }, [structures, inputFile, primaryFileName])

  const handleInputFileChange = useCallback((file: string) => {
    userPickedInputRef.current = true
    setInputFile(file)
  }, [])

  const categories = useMemo(() => Array.from(new Set(commands.map(command => command.category))), [commands])
  const visibleCommands = useMemo(() => commands.filter(command => command.category === category), [commands, category])
  const activeCmd = visibleCommands[tabIdx]
  const activeValues = useMemo(() => activeCmd ? values[activeCmd.name] ?? {} : {}, [activeCmd, values])

  useEffect(() => { setTabIdx(0) }, [category])

  const setFlagValue = useCallback((cmd: string, flag: string, v: any) => {
    const command = commands.find(item => item.name === cmd)
    const selected = command?.flags.find(item => item.flag === flag)
    setValues(prev => {
      const next = { ...(prev[cmd] ?? {}), [flag]: v }
      if (v && selected?.exclusiveGroup) {
        for (const peer of command?.flags ?? []) {
          if (peer.flag !== flag && peer.exclusiveGroup === selected.exclusiveGroup) {
            next[peer.flag] = false
          }
        }
      }
      return { ...prev, [cmd]: next }
    })
  }, [commands])

  const setInputValue = useCallback((cmd: string, dest: string, value: string | string[]) => {
    setInputsByCommand(prev => ({ ...prev, [cmd]: { ...(prev[cmd] ?? {}), [dest]: value } }))
  }, [])

  /* ── Model tab: per-chain FASTA inputs ─────────────────────────────
   * The model command takes --fasta <path>. To save users the hassle
   * of writing a FASTA file themselves, we render a textarea per chain
   * of the loaded primary structure. The contents are concatenated into
   * a real FASTA string and shipped as `fastaContent` in the request
   * body; the backend writes it to a file beside the output and injects
   * `--fasta <path>` into the args automatically.
   */
  const primaryChains = useStructureStore((s) => s.chains)
  const primaryFileNameStore = useStructureStore((s) => s.fileName)
  const inputMatchesLoaded = !!primaryFileNameStore && primaryFileNameStore === inputFile

  // Polypeptide chains only; drops water/ion/glycan etc.
  const seqChains = useMemo(() => {
    if (!inputMatchesLoaded) return []
    return filterSequenceableChains(primaryChains)
  }, [primaryChains, inputMatchesLoaded])

  // Map<chainId, sequence string>. Edited by the user.
  const [fastaByChain, setFastaByChain] = useState<Record<string, string>>({})
  // Snapshot of the LAST Parse from PDB output per chain, used to gate
  // inline missing-residue highlighting. As long as the textarea value
  // equals this snapshot, the underlay renders per-character colors;
  // once the user edits, the box reverts to plain text so user-typed
  // characters don't get mis-classified as "missing".
  const [parsedSequenceByChain, setParsedSequenceByChain] = useState<Record<string, string>>({})
  const [presentMapByChain, setPresentMapByChain] = useState<Record<string, boolean[]>>({})

  // Reset when the user switches inputs (different structure → different chains).
  useEffect(() => {
    setFastaByChain({})
    setParsedSequenceByChain({})
    setPresentMapByChain({})
  }, [inputFile])

  const parseFromPdb = useCallback(() => {
    if (seqChains.length === 0) return
    const next: Record<string, string> = {}
    const parsed: Record<string, string> = {}
    const present: Record<string, boolean[]> = {}
    for (const c of seqChains) {
      // Use the full SEQRES-aware sequence (chainToSequence maps every
      // compId to a 1-letter code; SEQRES-only residues get included
      // since they're already in c.residues with present:false).
      const seq = chainToSequence(c.residues)
      next[c.id] = seq
      parsed[c.id] = seq
      // Treat undefined as present (only mark explicit `false` as missing);
      // filterSequenceableChains widens the residue type via its generic,
      // so TS can't see ChainData's `present: boolean` guarantee.
      present[c.id] = c.residues.map(r => (r as { present?: boolean }).present !== false)
    }
    setFastaByChain(next)
    setParsedSequenceByChain(parsed)
    setPresentMapByChain(present)
  }, [seqChains])

  const setChainFasta = useCallback((chainId: string, value: string) => {
    setFastaByChain(prev => ({ ...prev, [chainId]: value }))
  }, [])

  // Build the FASTA file content from the per-chain text fields. One
  // record per chain that has non-empty content. Wraps sequences at
  // 60 chars per FASTA convention. Returns '' when no chain is set
  // (no content shipped).
  const buildFastaContent = useCallback((): string => {
    const parts: string[] = []
    const inputBase = inputFile.replace(/\.(pdb|cif|mmcif)$/i, '').replace(/.*\//, '')
    for (const c of seqChains) {
      const raw = (fastaByChain[c.id] ?? '').replace(/\s+/g, '')
      if (raw.length === 0) continue
      parts.push(`>${inputBase}_${c.id}`)
      for (let i = 0; i < raw.length; i += 60) parts.push(raw.slice(i, i + 60))
    }
    return parts.length === 0 ? '' : parts.join('\n') + '\n'
  }, [seqChains, fastaByChain, inputFile])

  const handleRun = useCallback(async () => {
    if (!activeCmd || !workspace || jobActive || submitInFlightRef.current) return
    const runInputs: Record<string, string | string[]> = { ...(inputsByCommand[activeCmd.name] ?? {}) }
    if (activeCmd.inputs[0] && !activeCmd.inputs[0].multi && inputFile) runInputs[activeCmd.inputs[0].dest] = inputFile
    const missing = activeCmd.inputs.find(input => input.required && (
      runInputs[input.dest] === undefined || runInputs[input.dest] === '' ||
      (Array.isArray(runInputs[input.dest]) && runInputs[input.dest].length === 0)
    ))
    if (missing) { setError(`${missing.label} is required`); return }
    submitInFlightRef.current = true
    setSubmitting(true)
    setError(null)
    setResult(null)
    try {
      // For the `model` tab, materialise the per-chain text inputs into
      // a real FASTA string; backend writes it to a file and injects
      // --fasta automatically. Empty string = nothing shipped (backend
      // ignores).
      const fastaContent = activeCmd.name === 'model' ? buildFastaContent() : ''
      const { data, error: apiError, response } = await v1Client.POST(
        '/api/v1/workspaces/{workspaceId}/jobs', {
        params: { path: { workspaceId: workspace.id } },
        body: createManagedJobRequest(activeCmd.name, {
          workspaceId: workspace.id,
          inputFile,
          inputs: runInputs,
          values: workflowValues(activeCmd.name, activeValues),
          fastaContent,
        }),
      })
      if (apiError) {
        setError(apiError.error.message || `HTTP ${response.status}`)
      } else {
        setJob(data as ManagedJobRecord)
      }
    } catch (e: any) {
      setError(e.message ?? String(e))
    } finally {
      submitInFlightRef.current = false
      setSubmitting(false)
    }
  }, [activeCmd, inputFile, inputsByCommand, activeValues, buildFastaContent, jobActive, workspace])

  const cancelJob = useCallback(async () => {
    if (!job || !workspace || !isActiveManagedJob(job) || cancelling) return
    setCancelling(true)
    setError(null)
    try {
      const { data, error: apiError, response } = await v1Client.DELETE(
        '/api/v1/workspaces/{workspaceId}/jobs/{jobId}', {
          params: { path: { workspaceId: workspace.id, jobId: job.id } },
        },
      )
      if (apiError) throw new Error(apiError.error.message || `Cancel: HTTP ${response.status}`)
      setJob(data as ManagedJobRecord)
    } catch (reason: any) {
      setError(reason.message || String(reason))
      setCancelling(false)
    }
  }, [cancelling, job, workspace])

  const inputOptions = useMemo(() => structures.filter(s => s.kind !== 'folder' && !!s.file), [structures])

  if (commands.length === 0) {
    return (
      <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
        <CircularProgress size={20} />
        <Typography variant="caption" color="text.secondary">
          Loading DVBFixer command specs…
        </Typography>
        <Typography variant="caption" color="text.secondary">
          If this never finishes, check that the dev server has access to <code>/api/dvbfixer-spec</code>.
        </Typography>
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      <Box sx={{ px: 1, py: 0.75, borderBottom: 1, borderColor: 'divider' }}>
        <FormControl size="small" sx={{ minWidth: 230 }}>
          <InputLabel sx={{ fontSize: '0.75rem' }}>Workflow group</InputLabel>
          <Select
            label="Workflow group"
            value={category}
            onChange={(event) => setCategory(event.target.value)}
            sx={{ fontSize: '0.75rem' }}
          >
            {categories.map(item => <MenuItem key={item} value={item}>{item}</MenuItem>)}
          </Select>
        </FormControl>
      </Box>
      {/* Command tabs */}
      <Tabs
        value={tabIdx}
        onChange={(_e, v) => setTabIdx(v)}
        variant="scrollable"
        scrollButtons="auto"
        sx={{
          minHeight: 30,
          borderBottom: 1, borderColor: 'divider',
          '& .MuiTab-root': { minHeight: 30, py: 0.5, fontSize: '0.7rem', textTransform: 'none', fontWeight: 600 },
        }}
      >
        {visibleCommands.map(c => (<Tab key={c.name} label={c.label} />))}
      </Tabs>

      {/* Body */}
      <Box sx={{ flex: 1, overflow: 'auto', p: 1.5, display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        {activeCmd && (
          <>
            <Typography variant="caption" sx={{ color: 'text.secondary' }}>
              {activeCmd.description}
            </Typography>

            <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1, flexWrap: 'wrap' }}>
              {activeCmd.inputs.map((input, index) => {
                const multiple = input.multi || input.nargs === '+' || input.nargs === '*'
                const current = index === 0 && !multiple
                  ? inputFile
                  : (inputsByCommand[activeCmd.name]?.[input.dest] ?? (multiple ? [] : ''))
                return (
                  <FormControl key={input.dest} size="small" sx={{ minWidth: 240 }}>
                    <InputLabel sx={{ fontSize: '0.75rem' }}>{input.label}</InputLabel>
                    <Select
                      multiple={multiple}
                      label={input.label}
                      value={current}
                      onChange={(event) => {
                        const value = event.target.value as string | string[]
                        if (index === 0 && !multiple) handleInputFileChange(value as string)
                        else setInputValue(activeCmd.name, input.dest, value)
                      }}
                      sx={{ fontSize: '0.75rem' }}
                    >
                      {inputOptions.map(s => (
                        <MenuItem key={s.file} value={s.file} sx={{ fontSize: '0.75rem' }}>
                          {s.file}
                        </MenuItem>
                      ))}
                    </Select>
                    {input.help && <Typography variant="caption" sx={{ color: 'text.secondary', mt: 0.25, fontSize: '0.65rem' }}>{input.help}</Typography>}
                  </FormControl>
                )
              })}

              <Box sx={{ height: 40, display: 'flex', alignItems: 'center', transform: 'translateY(-3px)' }}>
                <Button
                  variant="contained"
                  size="small"
                  disabled={jobActive || submitting || activeCmd.inputs.some((input, index) => input.required && (
                    index === 0 && !(input.multi || input.nargs === '+' || input.nargs === '*')
                      ? !inputFile : !inputsByCommand[activeCmd.name]?.[input.dest]
                  ))}
                  onClick={handleRun}
                  startIcon={jobActive || submitting ? <CircularProgress size={12} sx={{ color: 'white' }} /> : <PlayArrowIcon sx={{ fontSize: 16 }} />}
                >
                  Run {activeCmd.label}
                </Button>
              </Box>

              {jobActive && (
                <Button
                  size="small"
                  color="error"
                  variant="outlined"
                  disabled={cancelling}
                  onClick={cancelJob}
                  startIcon={cancelling ? <CircularProgress size={12} /> : <CancelIcon sx={{ fontSize: 16 }} />}
                >
                  {cancelling ? 'Cancelling…' : 'Cancel'}
                </Button>
              )}

              <Box sx={{ height: 40, display: 'flex', alignItems: 'center', transform: 'translateY(-3px)' }}>
                <Tooltip title="Reload command specs (pick up new DVBFixer subcommands without page reload)">
                  <IconButton size="small" onClick={() => { fetchSpec(); reloadWorkspace().catch(() => {}) }}>
                    <RefreshIcon sx={{ fontSize: 16 }} />
                  </IconButton>
                </Tooltip>
              </Box>

              {job && (
                <Chip
                  label={managedJobStatusLabel(job)}
                  color={job.status === 'succeeded' ? 'success' : job.status === 'failed' ? 'error' : job.status === 'cancelled' ? 'default' : 'info'}
                  size="small"
                />
              )}
              {!job && result && result.ok && (
                <Chip label={`OK · ${result.outputFile}`} color="success" size="small" />
              )}
              {!job && result && !result.ok && (
                <Chip
                  label={result.movedTo ? `Exit ${result.exitCode} · moved to ${result.movedTo}` : `Exit ${result.exitCode}`}
                  color="error"
                  size="small"
                />
              )}
            </Box>

            {error && <Alert severity="error" sx={{ py: 0.25, fontSize: '0.75rem' }}>{error}</Alert>}

            <Divider />

            {/* Model tab — per-chain FASTA inputs. Renders ONLY for the
             *  `model` command. The user pastes / parses one sequence per
             *  chain; on Run those get concatenated into a FASTA file
             *  passed via --fasta. */}
            {activeCmd.name === 'model' && (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.secondary' }}>
                    Sequences per chain (--fasta)
                  </Typography>
                  <Box sx={{ flex: 1 }} />
                  <Tooltip title={inputMatchesLoaded
                    ? 'Populate the boxes below with sequences extracted from the loaded structure (SEQRES + ATOM merged via extractChains).'
                    : 'Load this structure into the primary 3D viewer first to enable parsing.'}>
                    <span>
                      <Button
                        size="small"
                        variant="outlined"
                        onClick={parseFromPdb}
                        disabled={!inputMatchesLoaded || seqChains.length === 0}
                      >
                        Parse from PDB
                      </Button>
                    </span>
                  </Tooltip>
                  <Tooltip title="Clear all chain boxes">
                    <span>
                      <Button
                        size="small"
                        variant="text"
                        onClick={() => {
                          setFastaByChain({})
                          setParsedSequenceByChain({})
                          setPresentMapByChain({})
                        }}
                        disabled={Object.keys(fastaByChain).length === 0}
                      >
                        Clear
                      </Button>
                    </span>
                  </Tooltip>
                </Box>

                {!inputMatchesLoaded && (
                  <Alert severity="info" sx={{ py: 0.25, fontSize: '0.7rem' }}>
                    Load the selected input into the primary 3D viewer to
                    edit per-chain sequences. (Currently the loaded
                    structure differs from the picked DVBFixer input —
                    the chain list isn't known.) You can still leave
                    everything empty and dvbfixer will fall back to
                    SEQRES from the input PDB.
                  </Alert>
                )}

                {inputMatchesLoaded && seqChains.length === 0 && (
                  <Alert severity="info" sx={{ py: 0.25, fontSize: '0.7rem' }}>
                    No polypeptide chains detected in the loaded
                    structure — nothing to feed into --fasta.
                  </Alert>
                )}

                {seqChains.length > 0 && (
                  <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 1 }}>
                    {seqChains.map(c => {
                      const value = fastaByChain[c.id] ?? ''
                      const len = value.replace(/\s+/g, '').length
                      return (
                        <HighlightedFastaInput
                          key={c.id}
                          label={`Chain ${c.id}${len > 0 ? ` · ${len} aa` : ''}`}
                          value={value}
                          onChange={(v) => setChainFasta(c.id, v)}
                          placeholder="Paste single-letter sequence (or click Parse from PDB)"
                          parsedSequence={parsedSequenceByChain[c.id]}
                          presentMap={presentMapByChain[c.id]}
                          minRows={4}
                        />
                      )
                    })}
                  </Box>
                )}
              </Box>
            )}

            {/* CLI fields retain argparse's semantic argument groups. */}
            {activeCmd.groups.map(group => {
              const fields = group.fields
                .map(flag => activeCmd.flags.find(field => field.flag === flag))
                .filter((field): field is FlagDef => !!field)
                .filter(field => !(activeCmd.name === 'model' && field.flag === '--fasta'))
                .filter(field => workflowOptionActive(activeCmd.name, field.flag, activeValues))
              if (fields.length === 0) return null
              return (
                <Box key={group.name} sx={{ border: 1, borderColor: 'divider', borderRadius: 1, p: 1 }}>
                  <Typography variant="caption" sx={{ display: 'block', fontWeight: 700, mb: 1 }}>
                    {group.name}
                  </Typography>
                  <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 1.5 }}>
                    {fields.map(field => (
                      <FlagControl
                        key={field.flag}
                        flag={field}
                        value={activeValues[field.flag]}
                        artifactOptions={inputOptions}
                        onChange={(value) => setFlagValue(activeCmd.name, field.flag, value)}
                      />
                    ))}
                  </Box>
                </Box>
              )
            })}

            {result && (result.stdout || result.stderr) && (
              <Box sx={{ mt: 1 }}>
                <Typography variant="caption" sx={{ fontWeight: 700, color: 'text.secondary' }}>
                  Output
                </Typography>
                {result.stdout && (
                  <Box component="pre" sx={{
                    bgcolor: '#fafafa', p: 1, mt: 0.5,
                    border: 1, borderColor: 'divider', borderRadius: 1,
                    fontSize: '0.7rem', whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto',
                  }}>{result.stdout}</Box>
                )}
                {result.stderr && (
                  <Box component="pre" sx={{
                    bgcolor: '#fff5f5', p: 1, mt: 0.5,
                    border: 1, borderColor: 'error.light', borderRadius: 1,
                    fontSize: '0.7rem', whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto',
                    color: 'error.dark',
                  }}>{result.stderr}</Box>
                )}
              </Box>
            )}
          </>
        )}
      </Box>
    </Box>
  )
}

function FlagControl({ flag, value, artifactOptions, onChange }: {
  flag: FlagDef
  value: any
  artifactOptions: StructureEntry[]
  onChange: (v: any) => void
}) {
  if (flag.type === 'bool') {
    return (
      <FormControlLabel
        control={
          <Checkbox
            size="small"
            checked={value === true}
            onChange={(e) => onChange(e.target.checked)}
          />
        }
        label={
          <Box>
            <Typography variant="caption" sx={{ display: 'block', fontSize: '0.75rem' }}>
              {flag.label}
            </Typography>
            <Typography variant="caption" sx={{ color: 'text.secondary', fontFamily: 'monospace', fontSize: '0.65rem' }}>
              {flag.flag}
            </Typography>
            {flag.help && <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary', fontSize: '0.65rem' }}>
              {flag.help}
            </Typography>}
          </Box>
        }
        sx={{ alignItems: 'flex-start', m: 0 }}
      />
    )
  }
  if (flag.type === 'artifact') {
    const multiple = flag.repeatable || flag.multi
    return (
      <FormControl size="small" fullWidth>
        <InputLabel sx={{ fontSize: '0.75rem' }}>{flag.label}</InputLabel>
        <Select
          multiple={multiple}
          label={flag.label}
          value={value ?? (multiple ? [] : '')}
          onChange={(event) => onChange(event.target.value)}
          sx={{ fontSize: '0.75rem' }}
        >
          {artifactOptions.map(option => (
            <MenuItem key={option.file} value={option.file} sx={{ fontSize: '0.75rem' }}>
              {option.file}
            </MenuItem>
          ))}
        </Select>
        {flag.help && <Typography variant="caption" sx={{ color: 'text.secondary', mt: 0.25, fontSize: '0.65rem' }}>{flag.help}</Typography>}
      </FormControl>
    )
  }
  if (flag.type === 'select') {
    return (
      <FormControl size="small" fullWidth>
        <InputLabel sx={{ fontSize: '0.75rem' }}>{flag.label}</InputLabel>
        <Select
          label={flag.label}
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value)}
          sx={{ fontSize: '0.75rem' }}
        >
          {flag.flag === '--diffusion-model' && <MenuItem value="">Auto</MenuItem>}
          {(flag.options ?? []).map(opt => (
            <MenuItem key={String(opt)} value={opt} sx={{ fontSize: '0.75rem' }}>{opt}</MenuItem>
          ))}
        </Select>
        {flag.help && <Typography variant="caption" sx={{ color: 'text.secondary', mt: 0.25, fontSize: '0.65rem' }}>{flag.help}</Typography>}
      </FormControl>
    )
  }
  // number / text
  return (
    <TextField
      size="small"
      label={flag.label}
      value={value ?? ''}
      onChange={(e) => onChange(flag.type === 'number' && !flag.repeatable ? (e.target.value === '' ? '' : Number(e.target.value)) : e.target.value)}
      type={flag.type === 'number' && !flag.repeatable ? 'number' : 'text'}
      slotProps={{
        ...(flag.type === 'number' ? { htmlInput: { step: flag.step, min: flag.min, max: flag.max } } : {}),
        inputLabel: { sx: { fontSize: '0.75rem' } },
      }}
      helperText={flag.help}
      sx={{ '& .MuiInputBase-input': { fontSize: '0.75rem' }, '& .MuiFormHelperText-root': { fontSize: '0.65rem' } }}
    />
  )
}
