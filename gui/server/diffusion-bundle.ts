import crypto from 'node:crypto'
import fs from 'node:fs'
import path from 'node:path'

/** Transport verification only: Python owns scientific validation and ranking. */
export function readDiffusionPublication(indexPath: string): {
  status: 'success' | 'validation_failed'
  primary: string | null
  candidates: string[]
  sidecars: Record<string, string>
} {
  const root = path.dirname(indexPath)
  const stat = fs.lstatSync(indexPath)
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size > 10_000_000) throw new Error('invalid diffusion bundle index')
  const index = JSON.parse(fs.readFileSync(indexPath, 'utf8'))
  if (index.schema_version !== 2 || !['success', 'validation_failed'].includes(index.status) ||
      !Array.isArray(index.candidates) || index.candidates.length < 1 || index.candidates.length > 1000) {
    throw new Error('invalid diffusion publication schema')
  }
  const candidates: string[] = []
  const sidecars: Record<string, string> = {}
  const seen = new Set<string>()
  for (const candidate of index.candidates) {
    if (candidate.validation_passed !== (index.status === 'success')) throw new Error('inconsistent diffusion validation status')
    for (const label of ['pdb', 'dat', 'provenance', 'sampler_trace']) {
      const reference = candidate[label]
      if (!reference || typeof reference.path !== 'string' || typeof reference.sha256 !== 'string' ||
          path.isAbsolute(reference.path) || reference.path.split(/[\\/]/).includes('..')) {
        throw new Error('invalid diffusion artifact reference')
      }
      const artifact = path.resolve(root, reference.path)
      if (!artifact.startsWith(`${path.resolve(root)}${path.sep}`) || seen.has(artifact)) throw new Error('invalid diffusion artifact path')
      seen.add(artifact)
      let component = root
      for (const part of reference.path.split(/[\\/]/)) {
        component = path.join(component, part)
        if (fs.lstatSync(component).isSymbolicLink()) throw new Error('diffusion artifact must not be a symlink')
      }
      const info = fs.lstatSync(artifact)
      if (!info.isFile() || info.nlink !== 1 || info.size > 1_000_000_000) throw new Error('invalid diffusion artifact file')
      const digest = crypto.createHash('sha256').update(fs.readFileSync(artifact)).digest('hex')
      if (digest !== reference.sha256) throw new Error('diffusion artifact digest mismatch')
      if (label === 'pdb') candidates.push(artifact)
    }
    sidecars[path.resolve(root, candidate.pdb.path)] = path.resolve(root, candidate.dat.path)
  }
  return { status: index.status, primary: index.status === 'success' ? candidates[0] : null, candidates, sidecars }
}
