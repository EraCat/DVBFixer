import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import Tooltip from '@mui/material/Tooltip'
import Typography from '@mui/material/Typography'
import BiotechIcon from '@mui/icons-material/Biotech'
import FormatListNumberedIcon from '@mui/icons-material/FormatListNumbered'
import ViewWeekIcon from '@mui/icons-material/ViewWeek'
import TableChartIcon from '@mui/icons-material/TableChart'
import AssessmentIcon from '@mui/icons-material/Assessment'
import TerminalIcon from '@mui/icons-material/Terminal'
import SettingsIcon from '@mui/icons-material/Settings'
import DataObjectIcon from '@mui/icons-material/DataObject'
import InsertDriveFileIcon from '@mui/icons-material/InsertDriveFile'
import type { WorkspaceArtifact } from '../stores/workspaceStore'
import { artifactPresentation, type ArtifactCategory } from '../lib/artifact-presentation'

const CATEGORIES = {
  structure: { icon: BiotechIcon, color: 'primary.main' },
  sequence: { icon: FormatListNumberedIcon, color: 'success.main' },
  alignment: { icon: ViewWeekIcon, color: 'success.main' },
  table: { icon: TableChartIcon, color: 'info.main' },
  report: { icon: AssessmentIcon, color: 'secondary.main' },
  log: { icon: TerminalIcon, color: 'text.secondary' },
  settings: { icon: SettingsIcon, color: 'text.secondary' },
  data: { icon: DataObjectIcon, color: 'info.main' },
  other: { icon: InsertDriveFileIcon, color: 'text.secondary' },
} satisfies Record<ArtifactCategory, { icon: typeof BiotechIcon; color: string }>

/** Compact identity cell: category shape, user name, then a persistent format badge. */
export function ArtifactFileIdentity({ artifact }: { artifact: WorkspaceArtifact }) {
  const presentation = artifactPresentation(artifact)
  const { icon: Icon, color } = CATEGORIES[presentation.category]
  return <Tooltip title={<Box sx={{ whiteSpace: 'pre-line' }}>{presentation.tooltip}</Box>}>
    <Box component="span" sx={{ display: 'flex', alignItems: 'center', gap: 1, flex: 1, minWidth: 0 }}>
      <Box component="span" role="img" aria-label={presentation.label}
        sx={{ display: 'inline-flex', color, flexShrink: 0 }}>
        <Icon sx={{ fontSize: 18 }} />
      </Box>
      <Typography component="span" variant="body2" noWrap sx={{ flex: 1, minWidth: 0 }}>
        {artifact.name}
      </Typography>
      <Chip component="span" label={presentation.format} size="small" variant="outlined"
        sx={{ minWidth: 52, maxWidth: 88, flexShrink: 0, fontFamily: 'ui-monospace, monospace', fontWeight: 600, color: 'text.secondary' }} />
    </Box>
  </Tooltip>
}
