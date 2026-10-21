import { spawnSync } from 'node:child_process'
import { commandConfiguration } from './dvbfixer-runner'

/** Fail before listening/opening a browser, without importing scientific backends. */
export function assertDvbfixerAvailable(environment: NodeJS.ProcessEnv = process.env): string {
  const { executable, prefix } = commandConfiguration(environment)
  const result = spawnSync(executable, [...prefix, '--version'], {
    env: environment, encoding: 'utf8', timeout: 5000, maxBuffer: 64 * 1024,
  })
  if (result.error || result.status !== 0) {
    const detail = result.error?.message || result.stderr?.trim() || `exit ${result.status}`
    throw new Error(
      `DVBfixer GUI cannot start: the dvbfixer CLI is unavailable.\n` +
      `Activate your dvbfixer environment, then start the GUI again:\n` +
      `  micromamba activate dvbfixer\n  npm run dev\n` +
      `If needed, install dvbfixer in that environment or set DVBFIXER_EXECUTABLE to its executable path.\n` +
      `CLI check: ${detail}`,
    )
  }
  const version = result.stdout.trim()
  if (!/^dvbfixer\s+\d+\.\d+\.\d+/i.test(version)) {
    throw new Error('DVBfixer GUI cannot start: the configured executable did not return a dvbfixer version. Check DVBFIXER_EXECUTABLE and DVBFIXER_ARGS.')
  }
  return version
}
