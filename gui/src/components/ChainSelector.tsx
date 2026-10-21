import FormControl from '@mui/material/FormControl'
import Select from '@mui/material/Select'
import MenuItem from '@mui/material/MenuItem'
import { useStructureStore } from '../stores/structureStore'
import { threeToOne } from '../lib/residue-codes'

const NON_SEQ_COMPS = new Set([
  'HOH', 'WAT', 'DOD', 'H2O',
  'ZN', 'MG', 'CA', 'FE', 'MN', 'CO', 'NI', 'CU', 'NA', 'K',
  'CL', 'BR', 'SO4', 'PO4', 'NO3', 'CD', 'HG', 'SR', 'BA',
])

export function ChainSelector({ value, onChange }: { value?: string | null; onChange?: (chainId: string) => void } = {}) { // @dsp obj-a1000008
  const allChains = useStructureStore((s) => s.chains)

  const chains = allChains
    .map(c => ({ ...c, residues: c.residues.filter(r => !NON_SEQ_COMPS.has(r.compId)) }))
    .filter(c => c.residues.length > 1)
    // Drop chains whose residues are all unknown (1-letter = 'X') —
    // typically glycans (NAG / BMA / MAN / ...), heme groups, etc.
    // Their "sequence" would just be a row of X's so they don't belong
    // in the Sequence panel's chain dropdown.
    .filter(c => c.residues.some(r => threeToOne(r.compId) !== 'X'))
    // Sort by chain id so users see A, B, C, ... regardless of the
    // order Mol* discovered them in.
    .sort((a, b) => a.id.localeCompare(b.id, undefined, { numeric: true, sensitivity: 'base' }))

  if (chains.length <= 1) return null

  return (
    <FormControl size="small" sx={{ minWidth: 100 }}>
      <Select
        value={value ?? ''}
        onChange={(e) => onChange?.(e.target.value)}
        inputProps={{ 'aria-label': 'Protein chain' }}
      >
        {chains.map((c) => (
          <MenuItem key={c.id} value={c.id} sx={{ fontSize: '0.75rem' }}>
            Chain {c.id} ({c.residues.length} residues)
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  )
}
