import { spawn } from 'node:child_process'

const DEFAULT_MAX_CONCURRENT_PROCESSES = 1
const MAX_CONCURRENT_PROCESSES = 64
const DEFAULT_MAX_QUEUED_PROCESSES = 16
const MAX_QUEUED_PROCESSES = 256
const SHUTDOWN_MESSAGE = 'DVBfixer server is shutting down'

export type DvbfixerRunFailure =
  | 'cancelled'
  | 'shutdown'
  | 'timeout'
  | 'spawn-error'
  | 'nonzero-exit'
  | 'overloaded'

export interface DvbfixerRunResult {
  code: number
  stdout: string
  stderr: string
  started: boolean
  failure?: DvbfixerRunFailure
}

interface ActiveProcess {
  terminate(reason: string, failure: DvbfixerRunFailure): void
  completed: Promise<void>
}

interface QueuedRun {
  start(): void
  rejectForShutdown(): void
  signal?: AbortSignal
  abort(): void
}

const activeProcesses = new Set<ActiveProcess>()
const queuedRuns: QueuedRun[] = []
let acceptingProcesses = true
let activePermits = 0
let maxQueuedProcesses = parseDvbfixerMaxQueuedProcesses(process.env.DVBFIXER_MAX_QUEUED_PROCESSES)

export interface DvbfixerProcessAdmissionSnapshot {
  active: number
  queued: number
  limit: number
  queueLimit: number
  accepting: boolean
}

export function getDvbfixerProcessAdmissionSnapshot(): DvbfixerProcessAdmissionSnapshot {
  return {
    active: activePermits, queued: queuedRuns.length, limit: maxConcurrentProcesses,
    queueLimit: maxQueuedProcesses, accepting: acceptingProcesses,
  }
}

export function parseDvbfixerMaxConcurrentProcesses(value: string | undefined): number {
  if (value === undefined) return DEFAULT_MAX_CONCURRENT_PROCESSES
  if (!/^[1-9]\d*$/.test(value)) {
    throw new Error('DVBFIXER_MAX_CONCURRENT_PROCESSES must be a positive integer')
  }
  const parsed = Number(value)
  if (!Number.isSafeInteger(parsed) || parsed > MAX_CONCURRENT_PROCESSES) {
    throw new Error(`DVBFIXER_MAX_CONCURRENT_PROCESSES must be at most ${MAX_CONCURRENT_PROCESSES}`)
  }
  return parsed
}

export function parseDvbfixerMaxQueuedProcesses(value: string | undefined): number {
  if (value === undefined) return DEFAULT_MAX_QUEUED_PROCESSES
  if (!/^[1-9]\d*$/.test(value)) throw new Error('DVBFIXER_MAX_QUEUED_PROCESSES must be a positive integer')
  const parsed = Number(value)
  if (!Number.isSafeInteger(parsed) || parsed > MAX_QUEUED_PROCESSES) {
    throw new Error(`DVBFIXER_MAX_QUEUED_PROCESSES must be at most ${MAX_QUEUED_PROCESSES}`)
  }
  return parsed
}

let maxConcurrentProcesses = parseDvbfixerMaxConcurrentProcesses(
  process.env.DVBFIXER_MAX_CONCURRENT_PROCESSES,
)

export function resetDvbfixerProcessAdmission(
  maxProcesses = parseDvbfixerMaxConcurrentProcesses(process.env.DVBFIXER_MAX_CONCURRENT_PROCESSES),
  maxQueued = parseDvbfixerMaxQueuedProcesses(process.env.DVBFIXER_MAX_QUEUED_PROCESSES),
): void {
  if (!Number.isSafeInteger(maxProcesses) || maxProcesses < 1 || maxProcesses > MAX_CONCURRENT_PROCESSES) {
    throw new Error(`DVBfixer process concurrency must be an integer between 1 and ${MAX_CONCURRENT_PROCESSES}`)
  }
  if (!Number.isSafeInteger(maxQueued) || maxQueued < 1 || maxQueued > MAX_QUEUED_PROCESSES) {
    throw new Error(`DVBfixer process queue limit must be an integer between 1 and ${MAX_QUEUED_PROCESSES}`)
  }
  if (activePermits !== 0 || activeProcesses.size !== 0 || queuedRuns.length !== 0) {
    throw new Error('Cannot reset DVBfixer process admission until all work is drained')
  }
  maxConcurrentProcesses = maxProcesses
  maxQueuedProcesses = maxQueued
  acceptingProcesses = true
}

export function initializeDvbfixerProcessAdmission(
  value: string | undefined = process.env.DVBFIXER_MAX_CONCURRENT_PROCESSES,
  queuedValue: string | undefined = process.env.DVBFIXER_MAX_QUEUED_PROCESSES,
): void {
  resetDvbfixerProcessAdmission(
    parseDvbfixerMaxConcurrentProcesses(value), parseDvbfixerMaxQueuedProcesses(queuedValue),
  )
}

function rejectionResult(
  message: string,
  failure: 'cancelled' | 'shutdown' | 'overloaded',
): DvbfixerRunResult {
  return { code: -1, stdout: '', stderr: message, started: false, failure }
}

function drainQueue(): void {
  while (acceptingProcesses && activePermits < maxConcurrentProcesses && queuedRuns.length > 0) {
    const queued = queuedRuns.shift()
    if (!queued) return
    queued.signal?.removeEventListener('abort', queued.abort)
    if (queued.signal?.aborted) queued.abort()
    else {
      activePermits += 1
      queued.start()
    }
  }
}

export async function shutdownDvbfixerProcesses(): Promise<void> {
  acceptingProcesses = false
  for (const queued of queuedRuns.splice(0)) {
    queued.signal?.removeEventListener('abort', queued.abort)
    queued.rejectForShutdown()
  }
  const processes = [...activeProcesses]
  for (const process of processes) {
    process.terminate('DVBfixer run stopped by server shutdown', 'shutdown')
  }
  await Promise.all(processes.map(process => process.completed))
}

export interface DvbfixerRunOptions {
  timeoutMs?: number
  maxOutputBytes?: number
  killGraceMs?: number
  signal?: AbortSignal
  onStart?: () => void
}

export function commandConfiguration(environment: NodeJS.ProcessEnv = process.env): { executable: string; prefix: string[] } {
  const executable = environment.DVBFIXER_EXECUTABLE || 'dvbfixer'
  let prefix: unknown = []
  if (environment.DVBFIXER_ARGS) {
    try { prefix = JSON.parse(environment.DVBFIXER_ARGS) } catch {
      throw new Error('DVBFIXER_ARGS must be a JSON array of strings')
    }
  }
  if (!Array.isArray(prefix) || !prefix.every(item => typeof item === 'string')) {
    throw new Error('DVBFIXER_ARGS must be a JSON array of strings')
  }
  return { executable, prefix }
}

function appendBounded(current: string, chunk: Buffer, limit: number): string {
  if (Buffer.byteLength(current) >= limit) return current
  const remaining = limit - Buffer.byteLength(current)
  const text = chunk.subarray(0, remaining).toString()
  return current + text + (chunk.length > remaining ? '\n[output truncated]\n' : '')
}

function spawnErrorMessage(error: unknown): string {
  if (error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT') {
    return `${String(error)}\nDVBfixer CLI could not start. Activate the dvbfixer environment before starting the GUI, or set DVBFIXER_EXECUTABLE to its executable path. Check that the working directory also exists.`
  }
  return String(error)
}

export function runDvbfixerArgs(
  command: string,
  args: string[],
  cwd = process.cwd(),
  options: DvbfixerRunOptions = {},
): Promise<DvbfixerRunResult> {
  if (!acceptingProcesses) return Promise.resolve(rejectionResult(SHUTDOWN_MESSAGE, 'shutdown'))
  if (options.signal?.aborted) {
    return Promise.resolve(rejectionResult('DVBfixer run cancelled', 'cancelled'))
  }
  if (activePermits >= maxConcurrentProcesses && queuedRuns.length >= maxQueuedProcesses) {
    return Promise.resolve(rejectionResult('DVBfixer process queue is full', 'overloaded'))
  }

  const { executable, prefix } = commandConfiguration()
  const commandArgs = [...prefix, command, ...args]
  const timeoutMs = options.timeoutMs ?? Number(process.env.DVBFIXER_TIMEOUT_MS || 30 * 60_000)
  const maxOutputBytes = options.maxOutputBytes ?? Number(process.env.DVBFIXER_MAX_OUTPUT_BYTES || 10 * 1024 * 1024)

  return new Promise((resolve) => {
    let admitted = false
    const queued: QueuedRun = {
      signal: options.signal,
      start: () => {
        admitted = true
        startAdmittedRun()
      },
      rejectForShutdown: () => resolve(rejectionResult(SHUTDOWN_MESSAGE, 'shutdown')),
      abort: () => {
        if (admitted) return
        const index = queuedRuns.indexOf(queued)
        if (index !== -1) queuedRuns.splice(index, 1)
        options.signal?.removeEventListener('abort', queued.abort)
        resolve(rejectionResult('DVBfixer run cancelled', 'cancelled'))
      },
    }

    const startAdmittedRun = () => {
      let child: ReturnType<typeof spawn> | undefined
      let stdout = ''
      let stderr = ''
      let settled = false
      let terminationReason = ''
      let terminationFailure: DvbfixerRunFailure | undefined
      let killTimer: ReturnType<typeof setTimeout> | undefined
      let completeProcess: (() => void) | undefined
      let permitReleased = false

      const releasePermit = () => {
        if (permitReleased) return
        permitReleased = true
        activePermits -= 1
        drainQueue()
      }
      const active: ActiveProcess = {
        terminate: (reason, failure) => terminate(reason, failure),
        completed: new Promise<void>(completed => { completeProcess = completed }),
      }
      const finish = (code: number, failure = terminationFailure) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        if (killTimer) clearTimeout(killTimer)
        options.signal?.removeEventListener('abort', abort)
        activeProcesses.delete(active)
        completeProcess?.()
        releasePermit()
        const result: DvbfixerRunResult = {
          code,
          stdout,
          stderr: terminationReason ? `${stderr}\n${terminationReason}`.trim() : stderr,
          started: true,
        }
        const resolvedFailure = failure ?? (code === 0 ? undefined : 'nonzero-exit')
        if (resolvedFailure) result.failure = resolvedFailure
        resolve(result)
      }
      const signalChild = (signal: NodeJS.Signals) => {
        if (!child) return
        if (process.platform !== 'win32' && child.pid) {
          try {
            process.kill(-child.pid, signal)
            return
          } catch { /* fall back to the direct child when it is still alive */ }
        }
        if (child.exitCode === null && child.signalCode === null) child.kill(signal)
      }
      const terminate = (reason: string, failure: DvbfixerRunFailure) => {
        if (settled || terminationReason) return
        terminationReason = reason
        terminationFailure = failure
        if (!child) {
          finish(-1)
          return
        }
        signalChild('SIGTERM')
        killTimer = setTimeout(() => {
          signalChild('SIGKILL')
        }, options.killGraceMs ?? 5_000)
        killTimer.unref()
      }
      const abort = () => terminate('DVBfixer run cancelled', 'cancelled')
      const timer = setTimeout(
        () => terminate(`DVBfixer run timed out after ${timeoutMs} ms`, 'timeout'),
        timeoutMs,
      )

      activeProcesses.add(active)
      options.signal?.addEventListener('abort', abort, { once: true })
      if (options.signal?.aborted) {
        abort()
        return
      }
      try {
        options.onStart?.()
        if (settled) return
        child = spawn(executable, commandArgs, { cwd, detached: process.platform !== 'win32' })
      } catch (error) {
        terminationReason = spawnErrorMessage(error)
        finish(-1, 'spawn-error')
        return
      }
      child.stdout?.on('data', (data: Buffer) => { stdout = appendBounded(stdout, data, maxOutputBytes) })
      child.stderr?.on('data', (data: Buffer) => { stderr = appendBounded(stderr, data, maxOutputBytes) })
      child.on('error', error => {
        terminationReason = spawnErrorMessage(error)
        finish(-1, 'spawn-error')
      })
      child.on('close', code => {
        if (terminationReason) signalChild('SIGKILL')
        finish(code ?? -1)
      })
    }

    options.signal?.addEventListener('abort', queued.abort, { once: true })
    queuedRuns.push(queued)
    drainQueue()
  })
}

export function runDvbfixer(
  command: string,
  inputFile: string,
  outputFile: string,
  extraArgs: string[],
  options: DvbfixerRunOptions = {},
): Promise<DvbfixerRunResult> {
  return runDvbfixerArgs(command, [inputFile, '-o', outputFile, ...extraArgs], process.cwd(), options)
}
