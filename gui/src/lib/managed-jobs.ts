export type ManagedJobStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'

export interface ManagedJobRecord {
  version: 1
  id: string
  workspaceId: string
  status: ManagedJobStatus
  createdAt: string
  startedAt: string | null
  finishedAt: string | null
  command: string
  args: string[]
  exitCode: number | null
  stdoutLog: string
  stderrLog: string
  outputDir: string
  outputFile: string | null
  provenance?: { outputs: Array<{ artifactId: string; file: string; sha256: string }> }
  error?: string
}

export interface ManagedJobRequestPayload {
  workspaceId: string
  command: string
  inputFile: string
  inputs: Record<string, string | string[]>
  values: Record<string, unknown>
  fastaContent: string
}

/** Build the managed-job wire payload with the selected command included. */
export function createManagedJobRequest(
  command: string,
  request: Omit<ManagedJobRequestPayload, 'command'>,
): ManagedJobRequestPayload {
  return { ...request, command }
}

export function isActiveManagedJob(job: ManagedJobRecord | null | undefined): boolean {
  return job?.status === 'queued' || job?.status === 'running'
}

/** Prefer the active run when restoring a panel; otherwise show the newest recorded run. */
export function selectRestoredManagedJob(jobs: readonly ManagedJobRecord[]): ManagedJobRecord | null {
  return jobs.find(isActiveManagedJob) || jobs[0] || null
}

export function managedJobStatusLabel(job: ManagedJobRecord): string {
  if (job.status === 'queued') return `Queued · ${job.command}`
  if (job.status === 'running') return `Running · ${job.command}`
  if (job.status === 'succeeded') return `Completed · ${job.outputFile || job.command}`
  if (job.status === 'cancelled') return `Cancelled · ${job.command}`
  return `Failed${job.exitCode === null ? '' : ` (exit ${job.exitCode})`} · ${job.command}`
}
