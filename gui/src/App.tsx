import { useRef, useEffect, useCallback, useState } from 'react'
import { Layout, Model, TabNode, TabSetNode, Actions, DockLocation, type IJsonModel, type ITabSetRenderValues } from 'flexlayout-react'
import type { BorderNode } from 'flexlayout-react'
import 'flexlayout-react/style/light.css'
import AppBar from '@mui/material/AppBar'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import Box from '@mui/material/Box'
import CircularProgress from '@mui/material/CircularProgress'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import ViewInArIcon from '@mui/icons-material/ViewInAr'
import TextSnippetIcon from '@mui/icons-material/TextSnippet'
import ListAltIcon from '@mui/icons-material/ListAlt'
import HubIcon from '@mui/icons-material/Hub'
import WarningIcon from '@mui/icons-material/Warning'
import FolderIcon from '@mui/icons-material/Folder'
import FolderOpenIcon from '@mui/icons-material/FolderOpen'
import InfoIcon from '@mui/icons-material/Info'
import CompareArrowsIcon from '@mui/icons-material/CompareArrows'
import BuildIcon from '@mui/icons-material/Build'
import BiotechIcon from '@mui/icons-material/Biotech'
import SettingsIcon from '@mui/icons-material/Settings'
import LinkIcon from '@mui/icons-material/Link'
import LinkOffIcon from '@mui/icons-material/LinkOff'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import { MolstarViewer } from './components/MolstarViewer'
import { SequenceViewer } from './components/SequenceViewer'
import { FileLoader } from './components/FileLoader'
import { WorkspaceFileDrop } from './components/WorkspaceFileDrop'
import { ProjectLibrary, WorkspacePanel } from './components/ProjectLibrary'
import { StructureInfo } from './components/StructureInfo'
import { ElementsTable } from './components/ElementsTable'
import { InteractionsPanel } from './components/InteractionsPanel'
import { ClashesPanel } from './components/ClashesPanel'
import { AlignmentPanel } from './components/AlignmentPanel'
import { DVBFixerPanel } from './components/DVBFixerPanel'
import { HomologyPanel } from './components/HomologyPanel'
import { SettingsPanel } from './components/SettingsPanel'
import { TextFileViewer } from './components/TextFileViewer'
import { useStructureStore } from './stores/structureStore'
import { useSelectionStore } from './stores/selectionStore'
import { useMolstarSync } from './hooks/useMolstarSync'
import { useSequenceSync } from './hooks/useSequenceSync'
import { useCameraSync } from './hooks/useCameraSync'
import { useWorkspaceStore } from './stores/workspaceStore'
import { DEFAULT_MAIN_PANELS, PANEL_DEFINITIONS } from './app-panels'

const PANEL_ICONS = {
  viewer: ViewInArIcon, viewer2: ViewInArIcon, sequence: TextSnippetIcon,
  'text-viewer': TextSnippetIcon, elements: ListAltIcon, interactions: HubIcon,
  clashes: WarningIcon, alignment: CompareArrowsIcon, dvbfixer: BuildIcon,
  homology: BiotechIcon, library: FolderIcon, workspace: FolderOpenIcon,
  info: InfoIcon, settings: SettingsIcon,
}

const PANEL_TYPES = PANEL_DEFINITIONS.map(panel => {
  const Icon = PANEL_ICONS[panel.component]
  return { ...panel, icon: <Icon sx={{ fontSize: 16 }} /> }
})

let tabCounter = 0

const layoutJson: IJsonModel = {
  global: {
    tabEnableRename: false,
    tabSetEnableMaximize: true,
    tabSetEnableClose: true,
    splitterSize: 4,
    tabEnableClose: true,
  },
  borders: [],
  layout: {
    type: 'row',
    weight: 100,
    children: [
      {
        type: 'row',
        weight: 22,
        children: [
          {
            type: 'tabset',
            weight: 55,
            children: [
              { type: 'tab', name: 'Library', component: 'library' },
              { type: 'tab', name: 'Workspace', component: 'workspace' },
            ],
          },
          {
            type: 'tabset',
            weight: 45,
            children: [
              { type: 'tab', name: 'Info', component: 'info' },
              { type: 'tab', name: 'Text Files', component: 'text-viewer' },
              { type: 'tab', name: 'Settings', component: 'settings' },
            ],
          },
        ],
      },
      {
        type: 'row',
        weight: 78,
        children: [
          {
            type: 'tabset',
            weight: 65,
            children: DEFAULT_MAIN_PANELS.map(panel => ({ type: 'tab' as const, ...panel })),
          },
          {
            type: 'row',
            weight: 35,
            children: [
              {
                type: 'tabset',
                weight: 50,
                children: [
                  { type: 'tab', name: 'Sequence', component: 'sequence' },
                  { type: 'tab', name: 'Alignment', component: 'alignment' },
                ],
              },
              {
                type: 'tabset',
                weight: 50,
                children: [
                  { type: 'tab', name: 'Elements', component: 'elements' },
                  { type: 'tab', name: 'Interactions', component: 'interactions' },
                  { type: 'tab', name: 'Clashes', component: 'clashes' },
                ],
              },
            ],
          },
        ],
      },
    ],
  },
}

function App() { // @dsp obj-a1000002
  const modelRef = useRef(Model.fromJson(layoutJson))
  const plugin = useStructureStore((s) => s.plugin)
  const secondaryPlugin = useStructureStore((s) => s.secondaryPlugin)
  const cameraSyncEnabled = useStructureStore((s) => s.cameraSyncEnabled)
  const setCameraSyncEnabled = useStructureStore((s) => s.setCameraSyncEnabled)
  const isLoading = useStructureStore((s) => s.isLoading)
  const error = useStructureStore((s) => s.error)
  const fileName = useStructureStore((s) => s.fileName)
  const clearSelection = useSelectionStore((s) => s.clearSelection)
  const initializeWorkspace = useWorkspaceStore((s) => s.initialize)

  const [menuAnchor, setMenuAnchor] = useState<HTMLElement | null>(null)
  const [menuTabSetId, setMenuTabSetId] = useState<string | null>(null)

  useMolstarSync()
  useSequenceSync()
  useCameraSync()

  useEffect(() => {
    initializeWorkspace().catch(() => {})
  }, [initializeWorkspace])

  useEffect(() => {
    const openTextViewer = () => {
      let target: TabNode | null = null
      modelRef.current.visitNodes(node => {
        if (node instanceof TabNode && node.getComponent() === 'text-viewer') target = node
      })
      if (target) modelRef.current.doAction(Actions.selectTab((target as TabNode).getId()))
    }
    window.addEventListener('dvbfixer:open-text-viewer', openTextViewer)
    return () => window.removeEventListener('dvbfixer:open-text-viewer', openTextViewer)
  }, [])

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        clearSelection()
        if (plugin) {
          plugin.managers.interactivity.lociSelects.deselectAll()
          plugin.managers.interactivity.lociHighlights.clearHighlights()
          plugin.managers.structure.focus.behaviors.current.next(undefined)
          plugin.managers.structure.focus.clear()
          // Also remove "Show Interface" and sequence-selection sticks
          import('./lib/molstar-helpers').then(m => {
            m.clearInterfaceFocus(plugin).catch(() => {})
            m.clearSelectionSticks(plugin).catch(() => {})
            m.clearSurroundings(plugin).catch(() => {})
            m.clearClashSticks(plugin).catch(() => {})
          }).catch(() => {})
          useStructureStore.getState().setFocusedChain(null)
        }
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [clearSelection, plugin])

  const factory = useCallback((node: TabNode) => {
    switch (node.getComponent()) {
      case 'viewer': return <MolstarViewer slot="primary" />
      case 'viewer2': return <MolstarViewer slot="secondary" />
      case 'sequence': return <SequenceViewer />
      case 'text-viewer': return <TextFileViewer />
      case 'library': return <ProjectLibrary />
      case 'workspace': return <WorkspacePanel />
      case 'info': return <StructureInfo />
      case 'elements': return <ElementsTable />
      case 'interactions': return <InteractionsPanel />
      case 'clashes': return <ClashesPanel />
      case 'alignment': return <AlignmentPanel />
      case 'dvbfixer': return <DVBFixerPanel />
      case 'homology': return <HomologyPanel />
      case 'settings': return <SettingsPanel />
      default: return null
    }
  }, [])

  const handleAddPanel = useCallback((component: string, name: string) => {
    if (!menuTabSetId) return
    tabCounter++
    modelRef.current.doAction(
      Actions.addNode(
        { type: 'tab', name, component, id: `${component}-${tabCounter}` },
        menuTabSetId,
        DockLocation.CENTER,
        -1,
        true
      )
    )
    setMenuAnchor(null)
    setMenuTabSetId(null)
  }, [menuTabSetId])

  const onRenderTabSet = useCallback((node: TabSetNode | BorderNode, renderValues: ITabSetRenderValues) => {
    if (node instanceof TabSetNode) {
      renderValues.stickyButtons.push(
        <button
          key="add-tab"
          className="flexlayout__tab_toolbar_button"
          title="Add panel"
          onClick={(e) => {
            setMenuAnchor(e.currentTarget)
            setMenuTabSetId(node.getId())
          }}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: 20,
            height: 20,
            border: 'none',
            background: 'transparent',
            cursor: 'pointer',
            fontSize: 16,
            fontWeight: 300,
            padding: 0,
          }}
        >
          +
        </button>
      )
    }
  }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}>
      <WorkspaceFileDrop />
      <AppBar position="static" elevation={0} sx={{ bgcolor: 'background.paper', borderBottom: 1, borderColor: 'divider', flexShrink: 0 }}>
        <Toolbar variant="dense" sx={{ minHeight: 36, gap: 2 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 700, letterSpacing: 2, textTransform: 'uppercase', fontSize: '0.7rem', color: '#1D3261' }}>
            DVBfixer GUI
          </Typography>
          <Box sx={{ flex: 1 }} />
          {isLoading && <CircularProgress size={14} />}
          {error && <Typography variant="caption" sx={{ color: 'error.main' }}>{error}</Typography>}
          {fileName && (
            <>
              <Typography variant="caption" sx={{ color: '#1D3261', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
                {fileName}
              </Typography>
              <Box sx={{ width: '1px', height: 16, bgcolor: '#1D3261', flexShrink: 0 }} />
            </>
          )}
          {plugin && secondaryPlugin && (
            <Tooltip title={cameraSyncEnabled ? 'Camera sync ON — viewers move together (click to unlink)' : 'Camera sync OFF (click to link)'}>
              <IconButton
                size="small"
                onClick={() => setCameraSyncEnabled(!cameraSyncEnabled)}
                sx={{
                  p: 0.5,
                  color: cameraSyncEnabled ? 'primary.main' : 'text.secondary',
                  bgcolor: cameraSyncEnabled ? 'action.selected' : 'transparent',
                }}
              >
                {cameraSyncEnabled
                  ? <LinkIcon sx={{ fontSize: 16 }} />
                  : <LinkOffIcon sx={{ fontSize: 16 }} />
                }
              </IconButton>
            </Tooltip>
          )}
          <FileLoader />
        </Toolbar>
      </AppBar>

      <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        <Layout
          model={modelRef.current}
          factory={factory}
          onRenderTabSet={onRenderTabSet}
        />
      </div>

      <Menu
        anchorEl={menuAnchor}
        open={Boolean(menuAnchor)}
        onClose={() => { setMenuAnchor(null); setMenuTabSetId(null) }}
        sx={{ '& .MuiPaper-root': { minWidth: 160 } }}
      >
        {PANEL_TYPES.map(pt => (
          <MenuItem key={pt.component} onClick={() => handleAddPanel(pt.component, pt.name)} sx={{ fontSize: '0.75rem', py: 0.5 }}>
            <ListItemIcon sx={{ minWidth: 28 }}>{pt.icon}</ListItemIcon>
            <ListItemText sx={{ '& .MuiTypography-root': { fontSize: '0.75rem' } }}>{pt.name}</ListItemText>
          </MenuItem>
        ))}
      </Menu>
    </div>
  )
}

export default App
