/** Filter inactive form controls; CLI remains authoritative for option validation. */
export function workflowOptionActive(command: string, flag: string, values: Record<string, unknown>): boolean {
  if (command !== 'model' && command !== 'zbs') return true
  const diffusion = values[command === 'model' ? '--backend' : '--model-backend'] === 'diffusion'
  if (flag.startsWith('--diffusion-')) return diffusion
  const modeller = new Set(['--num-models', '--num-loops', '--num-output', '--md-level', '--pin-input', '--no-pin-input'])
  if (diffusion && modeller.has(flag)) return false
  if (command === 'zbs' && diffusion && flag === '--skip-model') return false
  if (command === 'model' && diffusion && ['--number-from-1', '--keep-water', '--no-infer-conect', '--keep-workdir'].includes(flag)) return false
  return true
}

export function workflowValues(command: string, values: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(values).filter(([flag]) => workflowOptionActive(command, flag, values)))
}
